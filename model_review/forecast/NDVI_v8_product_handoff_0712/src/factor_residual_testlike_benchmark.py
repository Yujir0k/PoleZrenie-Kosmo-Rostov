"""E035: глобальная низкоранговая коррекция синхронных остатков между полями.

В отличие от E021, это не per-field graph/ridge. Матрица leave-one-event-out
residuals R[date, field] восстанавливается общей rank-k факторизацией.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from benchmark import load_bundle
from state_space_testlike_benchmark import (
    key_set,
    latest_sequence,
    linear_primary,
    private_query,
    testlike_query,
)


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'
RANKS = (2, 4, 8)


def residual_pivot(frame: pd.DataFrame, masked: set[tuple[str, pd.Timestamp]]) -> pd.DataFrame:
    """Строит временные остатки с исключением текущего события для всех доноров."""
    records: list[tuple[pd.Timestamp, str, float]] = []
    for polygon, group in frame.groupby('anon_polygon_id', sort=False):
        part = group.sort_values('date')
        keys = list(zip(part['anon_polygon_id'].astype(str), part['date'], strict=True))
        observed = part['primary_ndvi'].notna().to_numpy() & ~np.fromiter(
            (key in masked for key in keys), dtype=bool, count=len(part)
        )
        values = part.loc[observed, 'primary_ndvi'].to_numpy(float)
        dates = part.loc[observed, 'date'].to_numpy()
        if len(values) < 3:
            continue
        # Значение i не используется для собственной базовой интерполяции.
        for index in range(1, len(values) - 1):
            left_date, right_date = pd.Timestamp(dates[index - 1]), pd.Timestamp(dates[index + 1])
            current_date = pd.Timestamp(dates[index])
            fraction = (current_date - left_date).days / (right_date - left_date).days
            baseline = values[index - 1] * (1. - fraction) + values[index + 1] * fraction
            records.append((current_date, str(polygon), float(values[index] - baseline)))
    residuals = pd.DataFrame(records, columns=['date', 'anon_polygon_id', 'residual'])
    return residuals.pivot(index='date', columns='anon_polygon_id', values='residual')


def low_rank_impute(pivot: pd.DataFrame, rank: int, iterations: int = 8) -> pd.DataFrame:
    """Заполняет SVD только пропуски, сохраняя реальные донорские значения."""
    matrix = pivot.to_numpy(float)
    observed = np.isfinite(matrix)
    count = observed.sum(axis=0)
    means = np.divide(
        np.nansum(matrix, axis=0), count, out=np.zeros(matrix.shape[1]), where=count > 0
    )
    centered = matrix - means
    filled = np.where(observed, centered, 0.)
    for _ in range(iterations):
        left, singular, right = np.linalg.svd(filled, full_matrices=False)
        reconstruction = (left[:, :rank] * singular[:rank]) @ right[:rank]
        filled[~observed] = reconstruction[~observed]
    return pd.DataFrame(filled + means, index=pivot.index, columns=pivot.columns)


def factor_prediction(factors: pd.DataFrame, query: pd.DataFrame) -> np.ndarray:
    prediction = np.zeros(len(query), dtype=float)
    for position, row in enumerate(query.itertuples(index=False)):
        if row.date in factors.index and str(row.anon_polygon_id) in factors.columns:
            value = factors.at[row.date, str(row.anon_polygon_id)]
            prediction[position] = value if np.isfinite(value) else 0.
    return prediction


def rmse(target: np.ndarray, prediction: np.ndarray) -> float:
    return float(np.sqrt(np.mean((target - prediction) ** 2)))


def evaluate(seed: int, private_mode: bool) -> tuple[dict[str, object], pd.DataFrame]:
    bundle = load_bundle(ROOT)
    query = private_query(bundle.private, seed) if private_mode else testlike_query(bundle.train, seed)
    masked = key_set(query)
    context = bundle.combined
    output = query[['anon_polygon_id', 'date', 'primary_ndvi']].rename(columns={'primary_ndvi': 'target'}).copy()
    output['linear_primary'] = linear_primary(context, query, masked)
    pivot = residual_pivot(context, masked)
    target = output['target'].to_numpy(float)
    scores: dict[str, float] = {'linear_primary': rmse(target, output['linear_primary'].to_numpy(float))}
    coverage: dict[str, float] = {}
    for rank in RANKS:
        correction = factor_prediction(low_rank_impute(pivot, rank), query)
        column = f'factor_rank_{rank}'
        output[column] = output['linear_primary'].to_numpy(float) + correction
        scores[column] = rmse(target, output[column].to_numpy(float))
        coverage[column] = float(np.mean(np.abs(correction) > 1e-12))
    metadata: dict[str, object] = {
        'seed': seed,
        'protocol': 'private auxiliary mask' if private_mode else '15% train test-like mask',
        'rows': len(output),
        'ranks': list(RANKS),
        'scores': scores,
        'nonzero_factor_coverage': coverage,
        'selected': min(scores, key=scores.get),
    }
    if private_mode:
        sequence = pd.read_parquet(latest_sequence(seed) / 'predictions.parquet')
        if not output[['anon_polygon_id', 'date']].equals(sequence[['anon_polygon_id', 'date']]):
            raise ValueError('Factorization и v5 validation имеют разные ключи')
        output['v5'] = .60 * sequence['current_v4'].to_numpy(float) + .40 * sequence['candidate'].to_numpy(float)
        v5 = output['v5'].to_numpy(float)
        factor = output['factor_rank_2'].to_numpy(float)
        metadata['scores']['v5'] = rmse(target, v5)
        metadata['factor_v5_error_correlation'] = float(np.corrcoef(target - factor, target - v5)[0, 1])
        metadata['v5_factor_blends'] = {
            str(weight): rmse(target, (1. - weight) * v5 + weight * factor)
            for weight in (.05, .10, .20, .30)
        }
    return metadata, output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--private', action='store_true')
    args = parser.parse_args()
    started = time.perf_counter()
    metadata, output = evaluate(args.seed, args.private)
    metadata['seconds'] = time.perf_counter() - started
    label = 'private' if args.private else 'testlike'
    directory = WORK / 'results' / f'factor_residual_{label}_{args.seed}_{time.strftime("%Y%m%d_%H%M%S")}'
    directory.mkdir(parents=True, exist_ok=True)
    output.to_parquet(directory / 'predictions.parquet', index=False)
    (directory / 'metrics.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)
    print(directory, flush=True)


if __name__ == '__main__':
    main()
