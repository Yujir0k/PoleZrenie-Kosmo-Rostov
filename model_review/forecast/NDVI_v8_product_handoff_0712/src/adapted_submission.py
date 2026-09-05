from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor

from benchmark import RANDOM_SEEDS, _feature_columns, build_features, load_bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Мультисенсорный private-adapted submission')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--work-dir', type=Path, default=Path(r'A:\cosmo_autogluon'))
    parser.add_argument(
        '--output',
        type=Path,
        default=Path(__file__).resolve().parents[1] / 'submission_v2_adapted.csv',
    )
    return parser.parse_args()


def key_set(frame: pd.DataFrame) -> set[tuple[str, pd.Timestamp]]:
    return set(zip(frame['anon_polygon_id'], frame['date'], strict=True))


def load_or_build_adaptation(
    root: Path,
    work_dir: Path,
) -> tuple[object, pd.DataFrame, pd.DataFrame]:
    bundle = load_bundle(root)
    cache_dir = work_dir / 'features_v2_private_final'
    cache_dir.mkdir(parents=True, exist_ok=True)
    known = bundle.private[
        (~bundle.private['is_synthetic_gap']) & bundle.private['primary_ndvi'].notna()
    ]
    sets: list[pd.DataFrame] = []
    for seed in RANDOM_SEEDS:
        path = cache_dir / f'adaptation_seed_{seed}.parquet'
        if path.exists():
            sets.append(pd.read_parquet(path))
            continue
        generator = np.random.default_rng(seed)
        count = round(len(known) * 0.15)
        selected = np.sort(
            generator.choice(known.index.to_numpy(), size=count, replace=False)
        )
        query = bundle.private.loc[selected].copy()
        features = build_features(
            bundle,
            query,
            key_set(query),
            f'private_final_adaptation_{seed}',
        )
        features.to_parquet(path, index=False)
        sets.append(features)
    adaptation = (
        pd.concat(sets, ignore_index=True)
        .drop_duplicates(['anon_polygon_id', 'date'], keep='first')
        .reset_index(drop=True)
    )

    hidden_path = cache_dir / 'hidden.parquet'
    query = bundle.private[bundle.private['is_synthetic_gap']].copy()
    if hidden_path.exists():
        hidden = pd.read_parquet(hidden_path)
    else:
        hidden = build_features(bundle, query, key_set(query), 'private_hidden_v2_adapted')
        hidden.to_parquet(hidden_path, index=False)
    return bundle, adaptation, hidden


def encode_categories(
    train: pd.DataFrame,
    hidden: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = train.copy()
    hidden = hidden.copy()
    for column in train.columns:
        if train[column].dtype == 'object' or hidden[column].dtype == 'object':
            categories = sorted(
                set(train[column].fillna('unknown').astype(str))
                | set(hidden[column].fillna('unknown').astype(str))
            )
            mapping = {value: index for index, value in enumerate(categories)}
            train[column] = train[column].fillna('unknown').astype(str).map(mapping)
            hidden[column] = hidden[column].fillna('unknown').astype(str).map(mapping)
    return train, hidden


def fit_lgb(
    base: pd.DataFrame,
    adaptation: pd.DataFrame,
    hidden: pd.DataFrame,
    columns: list[str],
    private_weight: float,
    iterations: int,
) -> np.ndarray:
    train = pd.concat([base, adaptation], ignore_index=True)
    weights = np.concatenate(
        [np.ones(len(base)), np.full(len(adaptation), private_weight)]
    )
    x_train, x_hidden = encode_categories(train[columns], hidden[columns])
    model = LGBMRegressor(
        n_estimators=iterations,
        learning_rate=0.025,
        num_leaves=31,
        max_depth=-1,
        min_child_samples=30,
        subsample=0.90,
        colsample_bytree=0.85,
        reg_lambda=6.0,
        random_state=2026,
        n_jobs=-1,
        verbosity=-1,
    )
    model.fit(x_train, train['target'], sample_weight=weights)
    return model.predict(x_hidden)


def fit_cat(
    base: pd.DataFrame,
    adaptation: pd.DataFrame,
    hidden: pd.DataFrame,
    columns: list[str],
) -> np.ndarray:
    train = pd.concat([base, adaptation], ignore_index=True)
    weights = np.concatenate([np.ones(len(base)), np.full(len(adaptation), 4.0)])
    x_train = train[columns].copy()
    x_hidden = hidden[columns].copy()
    categorical = [column for column in ('crop_type',) if column in columns]
    for column in categorical:
        x_train[column] = x_train[column].fillna('unknown').astype(str)
        x_hidden[column] = x_hidden[column].fillna('unknown').astype(str)
    categorical_indices = [x_train.columns.get_loc(column) for column in categorical]
    model = CatBoostRegressor(
        iterations=2500,
        depth=8,
        learning_rate=0.035,
        loss_function='RMSE',
        l2_leaf_reg=8,
        random_seed=2026,
        verbose=False,
        allow_writing_files=False,
        thread_count=-1,
    )
    model.fit(
        x_train,
        train['target'],
        sample_weight=weights,
        cat_features=categorical_indices,
    )
    return model.predict(x_hidden)


def main() -> None:
    args = parse_args()
    base_dir = args.work_dir / 'features_v2_sensor'
    base = (
        pd.concat(
            [
                pd.read_parquet(base_dir / f'train_seed_{seed}.parquet')
                for seed in RANDOM_SEEDS
            ],
            ignore_index=True,
        )
        .drop_duplicates(['anon_polygon_id', 'date'], keep='first')
        .reset_index(drop=True)
    )
    bundle, adaptation, hidden = load_or_build_adaptation(args.root, args.work_dir)
    columns = _feature_columns(pd.concat([base, adaptation], ignore_index=True))
    print(
        f'Обучение: train={len(base):,}, private-adapt={len(adaptation):,}, '
        f'hidden={len(hidden):,}, признаков={len(columns)}',
        flush=True,
    )

    lgb_half = fit_lgb(base, adaptation, hidden, columns, 0.5, 3900)
    print('LightGBM weight=0.5 готов', flush=True)
    lgb_two = fit_lgb(base, adaptation, hidden, columns, 2.0, 3000)
    print('LightGBM weight=2 готов', flush=True)
    cat_four = fit_cat(base, adaptation, hidden, columns)
    print('CatBoost weight=4 готов', flush=True)

    train_ids = set(bundle.train['anon_polygon_id'])
    seen = hidden['anon_polygon_id'].isin(train_ids).to_numpy()
    prediction = np.where(
        seen,
        0.60 * cat_four + 0.40 * lgb_two,
        0.58 * cat_four + 0.42 * lgb_half,
    )
    prediction = np.clip(prediction, -0.10, 0.95)
    query = bundle.private[bundle.private['is_synthetic_gap']].copy()
    submission = query[['anon_polygon_id', 'date']].copy()
    submission['date'] = submission['date'].dt.strftime('%Y-%m-%d')
    submission['primary_ndvi_true'] = prediction

    if len(submission) != 3112:
        raise ValueError(f'Некорректное количество строк: {len(submission)}')
    if submission.duplicated(['anon_polygon_id', 'date']).any():
        raise ValueError('Обнаружены дубли ключей')
    if not np.isfinite(submission['primary_ndvi_true']).all():
        raise ValueError('Обнаружены некорректные прогнозы')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    submission.to_csv(args.output, index=False, encoding='utf-8', float_format='%.10f')

    result_dir = args.work_dir / 'results' / f'adapted_final_{time.strftime("%Y%m%d_%H%M%S")}'
    result_dir.mkdir(parents=True, exist_ok=True)
    diagnostics = hidden[['anon_polygon_id', 'date', 'baseline_avg']].copy()
    diagnostics['lgb_half'] = lgb_half
    diagnostics['lgb_two'] = lgb_two
    diagnostics['cat_four'] = cat_four
    diagnostics['blend'] = prediction
    diagnostics.to_parquet(result_dir / 'predictions.parquet', index=False)
    metadata = {
        'rows_base': len(base),
        'rows_adaptation': len(adaptation),
        'rows_hidden': len(hidden),
        'features': len(columns),
        'prediction_min': float(prediction.min()),
        'prediction_max': float(prediction.max()),
        'prediction_mean': float(prediction.mean()),
        'output': str(args.output),
    }
    with (result_dir / 'metadata.json').open('w', encoding='utf-8') as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
