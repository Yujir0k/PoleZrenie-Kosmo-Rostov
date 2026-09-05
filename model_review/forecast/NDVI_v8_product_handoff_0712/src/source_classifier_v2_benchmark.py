from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import accuracy_score, log_loss, mean_squared_error

from benchmark import RANDOM_SEEDS, _feature_columns


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = PACKAGE_ROOT / 'work'
SOURCE_RUNS = {
    3030: WORK_DIR / 'results' / 'source_gating_20260904_224521',
    4040: WORK_DIR / 'results' / 'source_gating_20260904_225544',
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Физические признаки source classifier')
    parser.add_argument('--seed', type=int, choices=tuple(SOURCE_RUNS), required=True)
    return parser.parse_args()


def add_schedule_features(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    date = pd.to_datetime(output['date'])
    ordinal = (date - pd.Timestamp('2010-01-01')).dt.days
    output['date_event'] = date.dt.strftime('%Y-%m-%d')
    output['year_month'] = date.dt.strftime('%Y-%m')
    for period in (5, 8, 10, 16):
        output[f'orbit_mod_{period}'] = ordinal % period
    return output


def rmse(target: np.ndarray, prediction: np.ndarray) -> float:
    return float(mean_squared_error(target, prediction) ** 0.5)


def main() -> None:
    args = parse_args()
    base = (
        pd.concat(
            [
                pd.read_parquet(WORK_DIR / 'features_v2_sensor' / f'train_seed_{seed}.parquet')
                for seed in RANDOM_SEEDS
            ],
            ignore_index=True,
        )
        .drop_duplicates(['anon_polygon_id', 'date'], keep='first')
        .reset_index(drop=True)
    )
    directory = WORK_DIR / f'features_v2_private_adapt_{args.seed}'
    adaptation = (
        pd.concat(
            [pd.read_parquet(directory / f'adaptation_seed_{seed}.parquet') for seed in RANDOM_SEEDS],
            ignore_index=True,
        )
        .drop_duplicates(['anon_polygon_id', 'date'], keep='first')
        .reset_index(drop=True)
    )
    validation = pd.read_parquet(directory / 'validation.parquet')
    train = add_schedule_features(pd.concat([base, adaptation], ignore_index=True))
    validation = add_schedule_features(validation)
    columns = _feature_columns(train) + [
        'anon_polygon_id',
        'date_event',
        'year_month',
    ]
    # orbit_mod_* уже входят в _feature_columns после их добавления.
    columns = list(dict.fromkeys(columns))
    x_train = train[columns].copy()
    x_validation = validation[columns].copy()
    categorical = ['crop_type', 'anon_polygon_id', 'date_event', 'year_month']
    for column in categorical:
        x_train[column] = x_train[column].fillna('unknown').astype(str)
        x_validation[column] = x_validation[column].fillna('unknown').astype(str)
    weights = np.concatenate([np.ones(len(base)), np.full(len(adaptation), 4.0)])
    model = CatBoostClassifier(
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
    model.fit(
        x_train,
        train['target_source'],
        sample_weight=weights,
        cat_features=[x_train.columns.get_loc(column) for column in categorical],
    )
    probabilities = model.predict_proba(x_validation)
    classes = model.classes_.astype(str)
    predicted = classes[np.argmax(probabilities, axis=1)]
    source = pd.read_parquet(SOURCE_RUNS[args.seed] / 'predictions.parquet')
    gated_v2 = np.zeros(len(validation), dtype=float)
    for index, source_name in enumerate(classes):
        gated_v2 += probabilities[:, index] * source[f'pred_{source_name}'].to_numpy()
    old_gated = source['gated'].to_numpy()
    prior = source['prior_blend'].to_numpy()
    current_v3 = 0.47 * old_gated + 0.53 * prior
    target = validation['target'].to_numpy()
    best = (float('inf'), 0.0)
    for gated_weight in np.linspace(0.0, 1.0, 101):
        combined = gated_weight * gated_v2 + (1.0 - gated_weight) * prior
        value = rmse(target, combined)
        if value < best[0]:
            best = (value, float(gated_weight))
    fixed_v3 = 0.47 * gated_v2 + 0.53 * prior
    metrics = {
        'seed': args.seed,
        'old_accuracy': float(accuracy_score(validation['target_source'], source['predicted_source'])),
        'new_accuracy': float(accuracy_score(validation['target_source'], predicted)),
        'new_log_loss': float(log_loss(validation['target_source'], probabilities, labels=classes)),
        'old_gated_rmse': rmse(target, old_gated),
        'new_gated_rmse': rmse(target, gated_v2),
        'current_v3_rmse': rmse(target, current_v3),
        'fixed_weight_v3_rmse': rmse(target, fixed_v3),
        'diagnostic_best_blend_rmse': best[0],
        'diagnostic_gated_weight': best[1],
    }
    result_dir = WORK_DIR / 'results' / f'source_classifier_v2_{args.seed}_{time.strftime("%Y%m%d_%H%M%S")}'
    result_dir.mkdir(parents=True, exist_ok=True)
    output = validation[['anon_polygon_id', 'date', 'target', 'target_source', 'regime']].copy()
    output['old_gated'] = old_gated
    output['new_gated'] = gated_v2
    output['prior'] = prior
    output['current_v3'] = current_v3
    output['new_fixed_v3'] = fixed_v3
    output['predicted_source_v2'] = predicted
    for index, source_name in enumerate(classes):
        output[f'prob_{source_name}'] = probabilities[:, index]
    output.to_parquet(result_dir / 'predictions.parquet', index=False)
    with (result_dir / 'metrics.json').open('w', encoding='utf-8') as stream:
        json.dump(metrics, stream, ensure_ascii=False, indent=2)
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
    print(f'Результаты: {result_dir}', flush=True)


if __name__ == '__main__':
    main()
