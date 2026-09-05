"""E036: добавляет честный global rank-2 factor как feature в adapted prior v4."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from adapted_submission import fit_cat, fit_lgb
from benchmark import RANDOM_SEEDS, _feature_columns, load_bundle
from factor_residual_testlike_benchmark import factor_prediction, low_rank_impute, residual_pivot


ROOT = Path(__file__).resolve().parents[1]
WORK = Path(r'A:\cosmo_autogluon')
SOURCE_RUNS = {
    3030: WORK / 'results' / 'source_gating_20260904_224521',
    4040: WORK / 'results' / 'source_gating_20260904_225544',
}


def key_set(frame: pd.DataFrame) -> set[tuple[str, pd.Timestamp]]:
    return set(zip(frame['anon_polygon_id'].astype(str), frame['date'], strict=True))


def add_factor(bundle: object, features: pd.DataFrame, masked: set[tuple[str, pd.Timestamp]]) -> pd.DataFrame:
    """Вычисляет global factor строго из наблюдений вне внешней маски."""
    factors = low_rank_impute(residual_pivot(bundle.combined, masked), rank=2)
    output = features.copy()
    output['global_factor_rank2'] = factor_prediction(factors, output)
    return output


def factor_base(bundle: object) -> pd.DataFrame:
    """Каждая train synthetic mask получает factor из собственного masked context."""
    directory = WORK / 'features_v2_sensor'
    parts: list[pd.DataFrame] = []
    for seed in RANDOM_SEEDS:
        features = pd.read_parquet(directory / f'train_seed_{seed}.parquet')
        parts.append(add_factor(bundle, features, key_set(features)))
    return pd.concat(parts, ignore_index=True).drop_duplicates(['anon_polygon_id', 'date'], keep='first').reset_index(drop=True)


def factor_private(bundle: object, validation_seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validation скрыта во всех adaptation contexts ровно как в исходном cache."""
    directory = WORK / f'features_v2_private_adapt_{validation_seed}'
    validation = pd.read_parquet(directory / 'validation.parquet')
    validation_keys = key_set(validation)
    validation = add_factor(bundle, validation, validation_keys)
    parts: list[pd.DataFrame] = []
    for seed in RANDOM_SEEDS:
        features = pd.read_parquet(directory / f'adaptation_seed_{seed}.parquet')
        parts.append(add_factor(bundle, features, validation_keys | key_set(features)))
    adaptation = pd.concat(parts, ignore_index=True).drop_duplicates(['anon_polygon_id', 'date'], keep='first').reset_index(drop=True)
    return adaptation, validation


def factor_prior(base: pd.DataFrame, adaptation: pd.DataFrame, validation: pd.DataFrame) -> np.ndarray:
    """Тот же Cat/LGB prior v4 с единственным дополнительным factor feature."""
    columns = _feature_columns(pd.concat([base, adaptation], ignore_index=True))
    cat = fit_cat(base, adaptation, validation, columns)
    lgb_half = fit_lgb(base, adaptation, validation, columns, private_weight=.5, iterations=3900)
    lgb_two = fit_lgb(base, adaptation, validation, columns, private_weight=2., iterations=3000)
    seen_ids = set(base['anon_polygon_id'])
    seen = validation['anon_polygon_id'].isin(seen_ids).to_numpy()
    return np.where(seen, .60 * cat + .40 * lgb_two, .58 * cat + .42 * lgb_half)


def v4_with_prior(seed: int, validation: pd.DataFrame, prior: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    source = pd.read_parquet(SOURCE_RUNS[seed] / 'predictions.parquet')
    classifier_path = sorted((WORK / 'results').glob(f'source_classifier_v2_{seed}_*/predictions.parquet'))[-1]
    classifier = pd.read_parquet(classifier_path)
    for frame in (source, classifier):
        if not validation[['anon_polygon_id', 'date']].equals(frame[['anon_polygon_id', 'date']]):
            raise ValueError('Не совпали ключи source branch')
    probabilities = classifier[['prob_landsat', 'prob_modis', 'prob_s2']].to_numpy(float) ** (1. / .30)
    probabilities /= probabilities.sum(axis=1, keepdims=True)
    experts = source[['pred_landsat', 'pred_modis', 'pred_s2']].to_numpy(float)
    gated = np.sum(probabilities * experts, axis=1)
    current = .53 * classifier['prior'].to_numpy(float) + .47 * gated
    candidate = .53 * prior + .47 * gated
    return current, candidate


def rmse(target: np.ndarray, prediction: np.ndarray) -> float:
    return float(np.sqrt(np.mean((target - prediction) ** 2)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', required=True, type=int, choices=tuple(SOURCE_RUNS))
    parser.add_argument('--fixed-weight', type=float)
    args = parser.parse_args()
    started = time.perf_counter()
    bundle = load_bundle(ROOT)
    base = factor_base(bundle)
    adaptation, validation = factor_private(bundle, args.seed)
    prior = factor_prior(base, adaptation, validation)
    current, candidate = v4_with_prior(args.seed, validation, prior)
    target = validation['target'].to_numpy(float)
    weights = [args.fixed_weight] if args.fixed_weight is not None else np.linspace(0., 1., 21)
    blends = {f'{weight:.2f}': rmse(target, (1. - weight) * current + weight * candidate) for weight in weights}
    selected = min(blends, key=blends.get)
    directory = WORK / 'results' / f'factor_feature_prior_{args.seed}_{time.strftime("%Y%m%d_%H%M%S")}'
    directory.mkdir(parents=True, exist_ok=True)
    output = validation[['anon_polygon_id', 'date', 'target']].copy()
    output['global_factor_rank2'] = validation['global_factor_rank2']
    output['current_v4'] = current
    output['factor_prior_v4'] = candidate
    output.to_parquet(directory / 'predictions.parquet', index=False)
    metrics = {
        'seed': args.seed,
        'base_rows': len(base),
        'adaptation_rows': len(adaptation),
        'validation_rows': len(validation),
        'current_v4_rmse': rmse(target, current),
        'factor_prior_v4_rmse': rmse(target, candidate),
        'blend_scores': blends,
        'selected_weight': float(selected),
        'selected_rmse': blends[selected],
        'factor_nonzero_share_validation': float(np.mean(np.abs(validation['global_factor_rank2']) > 1e-12)),
        'seconds': time.perf_counter() - started,
    }
    (directory / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
    print(directory, flush=True)


if __name__ == '__main__':
    main()
