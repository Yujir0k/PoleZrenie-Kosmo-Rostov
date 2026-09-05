"""Воспроизводит подтверждённую архитектуру v7 для replacement test без утечек.

В replacement-файле нет климатологических столбцов организатора. Пайплайн не
восстанавливает их из целевой переменной и пересчитывает признаки для каждой
маски, поэтому разметка снятого теста не попадает в прогноз.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from lightgbm import LGBMRegressor

from adapted_submission import encode_categories, fit_cat, fit_lgb
from benchmark import (
    RANDOM_SEEDS,
    DatasetBundle,
    _feature_columns,
    build_features,
    build_peer_map,
    build_weather_clusters,
    exact_mask_indices,
    source_labels,
)
from factor_feature_prior_benchmark import add_factor
from source_classifier_v2_benchmark import add_schedule_features


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRAIN = PACKAGE_ROOT / 'data' / 'train_dataset.zip'
DEFAULT_TEST = PACKAGE_ROOT / 'data' / 'New_test.csv'
DEFAULT_WORK = PACKAGE_ROOT / 'work' / 'new_test_v7_clean'
DEFAULT_OUTPUT = PACKAGE_ROOT / 'output' / 'submission_v7_clean_new_test.csv'
DEFAULT_TORCH_PYTHON = Path(sys.executable)
CLIMATOLOGY_COLUMNS = ('ndvi_climatology_mean', 'ndvi_climatology_std')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Leak-free v7 for New_test.csv')
    parser.add_argument('--train-zip', type=Path, default=DEFAULT_TRAIN)
    parser.add_argument('--test', type=Path, default=DEFAULT_TEST)
    parser.add_argument('--work-dir', type=Path, default=DEFAULT_WORK)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--epochs', type=int, default=70)
    parser.add_argument('--width', type=int, default=56)
    parser.add_argument('--context', type=int, default=18)
    parser.add_argument('--torch-python', type=Path, default=DEFAULT_TORCH_PYTHON)
    parser.add_argument('--rebuild-features', action='store_true')
    return parser.parse_args()


def frame_keys(frame: pd.DataFrame) -> set[tuple[str, pd.Timestamp]]:
    return set(zip(frame['anon_polygon_id'].astype(str), frame['date'], strict=True))


def load_clean_bundle(train_zip: Path, test_path: Path) -> DatasetBundle:
    """Загружает исходный train и replacement test без удалённой климатологии."""
    with zipfile.ZipFile(train_zip) as archive:
        train = pd.read_csv(archive.open('train_dataset.csv'), parse_dates=['date'])
    private = pd.read_csv(test_path, parse_dates=['date'])
    required = {
        'anon_polygon_id',
        'date',
        'primary_ndvi',
        'is_synthetic_gap',
        'crop_type',
    }
    missing = required - set(private.columns)
    if missing:
        raise ValueError(f'New test is missing columns: {sorted(missing)}')
    if private.duplicated(['anon_polygon_id', 'date']).any():
        raise ValueError('New test contains duplicate polygon/date keys')

    train = train.copy()
    private = private.copy()
    # Организатор удалил эти столбцы после обнаружения утечки. Одинаковые NaN
    # в train и test убирают сдвиг по пропускам, поэтому модель опирается только
    # на безопасные исторические признаки, рассчитанные ниже.
    for column in CLIMATOLOGY_COLUMNS:
        train[column] = np.nan
        private[column] = np.nan
    train['source'] = source_labels(train)
    private['source'] = source_labels(private)
    train['target_source'] = train['source']
    private['target_source'] = private['source']
    private.loc[private['is_synthetic_gap'], ['source', 'target_source']] = 'hidden'

    common_columns = [
        'anon_polygon_id',
        'date',
        'primary_ndvi',
        *CLIMATOLOGY_COLUMNS,
        'era5_temp_c',
        'era5_precip_mm',
        's2_ndvi',
        's2_evi',
        's2_ndwi',
        'landsat_ndvi',
        'landsat_evi',
        'landsat_ndwi',
        'modis_ndvi',
        'modis_evi',
        'crop_type',
        'source',
    ]
    combined = (
        pd.concat([train[common_columns], private[common_columns]], ignore_index=True)
        .drop_duplicates(['anon_polygon_id', 'date'], keep='last')
        .sort_values(['anon_polygon_id', 'date'])
        .reset_index(drop=True)
    )
    combined['day'] = (combined['date'] - pd.Timestamp('2010-01-01')).dt.days
    combined['year_calc'] = combined['date'].dt.year
    combined['doy_calc'] = combined['date'].dt.dayofyear
    key_to_index = {
        (str(polygon), pd.Timestamp(date)): index
        for index, (polygon, date) in enumerate(
            zip(combined['anon_polygon_id'], combined['date'], strict=True)
        )
    }
    weather_cluster = build_weather_clusters(combined)
    peer_map = build_peer_map(combined)
    return DatasetBundle(
        train=train,
        private=private,
        combined=combined,
        key_to_index=key_to_index,
        peer_map=peer_map,
        weather_cluster=weather_cluster,
    )


def read_or_build(
    path: Path,
    builder: callable,
    rebuild: bool,
) -> pd.DataFrame:
    if path.exists() and not rebuild:
        frame = pd.read_parquet(path)
        print(f'Cache: {path.name} ({len(frame):,})', flush=True)
        return frame
    frame = builder()
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame


def build_feature_sets(
    bundle: DatasetBundle,
    work_dir: Path,
    rebuild: bool,
) -> tuple[list[pd.DataFrame], list[pd.DataFrame], pd.DataFrame]:
    feature_dir = work_dir / 'features'
    train_parts: list[pd.DataFrame] = []
    for seed in RANDOM_SEEDS:
        indices = exact_mask_indices(bundle.train, seed)
        query = bundle.train.loc[indices].copy()
        train_parts.append(
            read_or_build(
                feature_dir / f'train_seed_{seed}.parquet',
                lambda query=query, seed=seed: build_features(
                    bundle, query, frame_keys(query), f'new_clean_train_{seed}'
                ),
                rebuild,
            )
        )

    known = bundle.private.loc[
        (~bundle.private['is_synthetic_gap']) & bundle.private['primary_ndvi'].notna()
    ]
    adaptation_parts: list[pd.DataFrame] = []
    for seed in RANDOM_SEEDS:
        generator = np.random.default_rng(seed)
        count = round(len(known) * 0.15)
        selected = np.sort(
            generator.choice(known.index.to_numpy(), size=count, replace=False)
        )
        query = bundle.private.loc[selected].copy()
        adaptation_parts.append(
            read_or_build(
                feature_dir / f'adaptation_seed_{seed}.parquet',
                lambda query=query, seed=seed: build_features(
                    bundle, query, frame_keys(query), f'new_clean_adaptation_{seed}'
                ),
                rebuild,
            )
        )

    hidden_query = bundle.private.loc[bundle.private['is_synthetic_gap']].copy()
    hidden = read_or_build(
        feature_dir / 'hidden.parquet',
        lambda: build_features(
            bundle, hidden_query, frame_keys(hidden_query), 'new_clean_hidden'
        ),
        rebuild,
    )
    return train_parts, adaptation_parts, hidden


def first_key_occurrence(parts: list[pd.DataFrame]) -> pd.DataFrame:
    return (
        pd.concat(parts, ignore_index=True)
        .drop_duplicates(['anon_polygon_id', 'date'], keep='first')
        .reset_index(drop=True)
    )


def prior_prediction(
    base: pd.DataFrame,
    adaptation: pd.DataFrame,
    hidden: pd.DataFrame,
) -> np.ndarray:
    columns = _feature_columns(pd.concat([base, adaptation], ignore_index=True))
    cat = fit_cat(base, adaptation, hidden, columns)
    print('Prior CatBoost ready', flush=True)
    lgb_half = fit_lgb(base, adaptation, hidden, columns, 0.5, 3900)
    print('Prior LightGBM weight=0.5 ready', flush=True)
    lgb_two = fit_lgb(base, adaptation, hidden, columns, 2.0, 3000)
    print('Prior LightGBM weight=2 ready', flush=True)
    seen = hidden['anon_polygon_id'].isin(set(base['anon_polygon_id'])).to_numpy()
    return np.where(seen, 0.60 * cat + 0.40 * lgb_two, 0.58 * cat + 0.42 * lgb_half)


def source_branch(
    base: pd.DataFrame,
    adaptation: pd.DataFrame,
    hidden: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    train = pd.concat([base, adaptation], ignore_index=True)
    weights = np.concatenate([np.ones(len(base)), np.full(len(adaptation), 4.0)])
    regression_columns = _feature_columns(train)
    encoded_train, encoded_hidden = encode_categories(
        train[regression_columns], hidden[regression_columns]
    )
    classes = sorted(train['target_source'].astype(str).unique())
    expected_classes = {'s2', 'landsat', 'modis'}
    if set(classes) != expected_classes:
        raise ValueError(f'Unexpected target-source classes: {classes}')
    expert_predictions: dict[str, np.ndarray] = {}
    for source in classes:
        selected = train['target_source'].eq(source).to_numpy()
        model = LGBMRegressor(
            n_estimators=3500,
            learning_rate=0.025,
            num_leaves=31,
            min_child_samples=25,
            colsample_bytree=0.85,
            reg_lambda=7.0,
            random_state=2026,
            n_jobs=-1,
            verbosity=-1,
        )
        model.fit(
            encoded_train.loc[selected],
            train.loc[selected, 'target'],
            sample_weight=weights[selected],
        )
        expert_predictions[source] = model.predict(encoded_hidden)
        print(f'Source expert {source} ready ({selected.sum():,})', flush=True)

    scheduled_train = add_schedule_features(train)
    scheduled_hidden = add_schedule_features(hidden)
    classifier_columns = list(
        dict.fromkeys(
            _feature_columns(scheduled_train)
            + ['anon_polygon_id', 'date_event', 'year_month']
        )
    )
    x_train = scheduled_train[classifier_columns].copy()
    x_hidden = scheduled_hidden[classifier_columns].copy()
    categorical = ['crop_type', 'anon_polygon_id', 'date_event', 'year_month']
    for column in categorical:
        x_train[column] = x_train[column].fillna('unknown').astype(str)
        x_hidden[column] = x_hidden[column].fillna('unknown').astype(str)
    classifier = CatBoostClassifier(
        iterations=1500,
        depth=7,
        learning_rate=0.04,
        loss_function='MultiClass',
        l2_leaf_reg=7,
        random_seed=2026,
        verbose=False,
        allow_writing_files=False,
        thread_count=-1,
    )
    classifier.fit(
        x_train,
        scheduled_train['target_source'],
        sample_weight=weights,
        cat_features=[x_train.columns.get_loc(column) for column in categorical],
    )
    raw_probabilities = classifier.predict_proba(x_hidden)
    classifier_classes = classifier.classes_.astype(str).tolist()
    probabilities = raw_probabilities ** (1.0 / 0.30)
    probabilities /= probabilities.sum(axis=1, keepdims=True)
    gated = np.zeros(len(hidden), dtype=float)
    for index, source in enumerate(classifier_classes):
        gated += probabilities[:, index] * expert_predictions[source]
    print('Physical source classifier ready', flush=True)
    return gated, probabilities, classifier_classes


def sequence_prediction(
    args: argparse.Namespace,
    probabilities: np.ndarray,
    classifier_classes: list[str],
) -> np.ndarray:
    probability_path = args.work_dir / 'source_probabilities.npy'
    classes_path = args.work_dir / 'source_classes.json'
    output_path = args.work_dir / 'sequence_gated.npy'
    np.save(probability_path, probabilities)
    classes_path.write_text(
        json.dumps(classifier_classes, ensure_ascii=False), encoding='utf-8'
    )
    helper = Path(__file__).with_name('new_test_v7_sequence_stage.py')
    command = [
        str(args.torch_python),
        str(helper),
        '--train-zip',
        str(args.train_zip),
        '--test',
        str(args.test),
        '--probabilities',
        str(probability_path),
        '--classes',
        str(classes_path),
        '--output',
        str(output_path),
        '--epochs',
        str(args.epochs),
        '--width',
        str(args.width),
        '--context',
        str(args.context),
    ]
    subprocess.run(command, check=True)
    return np.load(output_path)


def factor_feature_sets(
    bundle: DatasetBundle,
    train_parts: list[pd.DataFrame],
    adaptation_parts: list[pd.DataFrame],
    hidden: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    factor_base = first_key_occurrence(
        [add_factor(bundle, part, frame_keys(part)) for part in train_parts]
    )
    factor_adaptation = first_key_occurrence(
        [add_factor(bundle, part, frame_keys(part)) for part in adaptation_parts]
    )
    factor_hidden = add_factor(bundle, hidden, frame_keys(hidden))
    return factor_base, factor_adaptation, factor_hidden


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    bundle = load_clean_bundle(args.train_zip, args.test)
    print(
        f'Data: train={len(bundle.train):,}; new_test={len(bundle.private):,}; '
        f'known={bundle.private.primary_ndvi.notna().sum():,}; '
        f'queries={bundle.private.is_synthetic_gap.sum():,}',
        flush=True,
    )
    train_parts, adaptation_parts, hidden = build_feature_sets(
        bundle, args.work_dir, args.rebuild_features
    )
    base = first_key_occurrence(train_parts)
    adaptation = first_key_occurrence(adaptation_parts)
    print(
        f'Model rows: base={len(base):,}; adaptation={len(adaptation):,}; '
        f'hidden={len(hidden):,}; features={len(_feature_columns(base))}',
        flush=True,
    )

    prior = prior_prediction(base, adaptation, hidden)
    gated, probabilities, classifier_classes = source_branch(base, adaptation, hidden)
    sequence_gated = sequence_prediction(args, probabilities, classifier_classes)
    v4 = np.clip(0.53 * prior + 0.47 * gated, -0.10, 0.95)
    sequence_candidate = np.clip(0.53 * prior + 0.47 * sequence_gated, -0.10, 0.95)
    v5 = np.clip(0.60 * v4 + 0.40 * sequence_candidate, -0.10, 0.95)

    factor_base, factor_adaptation, factor_hidden = factor_feature_sets(
        bundle, train_parts, adaptation_parts, hidden
    )
    factor_prior = prior_prediction(factor_base, factor_adaptation, factor_hidden)
    factor_v4 = np.clip(0.53 * factor_prior + 0.47 * gated, -0.10, 0.95)
    prediction = np.clip(v5 + factor_v4 - v4, -0.10, 0.95)

    query = bundle.private.loc[bundle.private['is_synthetic_gap'], ['anon_polygon_id', 'date']].copy()
    if not query.reset_index(drop=True).equals(
        hidden[['anon_polygon_id', 'date']].reset_index(drop=True)
    ):
        raise ValueError('Feature and submission key order mismatch')
    submission = query.copy()
    submission['date'] = submission['date'].dt.strftime('%Y-%m-%d')
    submission['primary_ndvi_true'] = prediction
    if len(submission) != int(bundle.private['is_synthetic_gap'].sum()):
        raise ValueError('Submission row count mismatch')
    if submission.duplicated(['anon_polygon_id', 'date']).any():
        raise ValueError('Submission contains duplicate keys')
    if not np.isfinite(prediction).all():
        raise ValueError('Submission contains NaN/inf predictions')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    submission.to_csv(args.output, index=False, encoding='utf-8', float_format='%.10f')

    diagnostics = hidden[['anon_polygon_id', 'date', 'baseline_avg', 'history_mean']].copy()
    diagnostics['prior'] = prior
    diagnostics['gated'] = gated
    diagnostics['sequence_gated'] = sequence_gated
    diagnostics['v4'] = v4
    diagnostics['v5'] = v5
    diagnostics['global_factor_rank2'] = factor_hidden['global_factor_rank2'].to_numpy(float)
    diagnostics['factor_prior'] = factor_prior
    diagnostics['final_v7_clean'] = prediction
    diagnostics.to_parquet(args.work_dir / 'predictions.parquet', index=False)
    metadata = {
        'pipeline': 'v7-clean',
        'leak_policy': 'withdrawn 2025 test excluded; organizer climatology columns disabled',
        'train_zip': str(args.train_zip),
        'test': str(args.test),
        'rows': int(len(submission)),
        'polygons': int(query['anon_polygon_id'].nunique()),
        'known_private_targets': int(bundle.private['primary_ndvi'].notna().sum()),
        'prediction_min': float(prediction.min()),
        'prediction_max': float(prediction.max()),
        'prediction_mean': float(prediction.mean()),
        'mean_abs_factor_change_from_v5': float(np.mean(np.abs(prediction - v5))),
        'factor_nonzero_share': float(
            np.mean(np.abs(factor_hidden['global_factor_rank2'].to_numpy(float)) > 1e-12)
        ),
        'seconds': float(time.perf_counter() - started),
        'output': str(args.output),
    }
    (args.work_dir / 'metadata.json').write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
