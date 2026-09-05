"""E034: test-faithful validation и линейный multi-sensor state-space imputer.

Состояние x_t — латентный дневной NDVI. Оценка является MAP-решением:
  sum_i w_i (y_i - x_ti)^2 + a ||x-c||^2 + b ||D(x-c)||^2,
где c — climatology, D — разность соседних дней. S2/Landsat/MODIS входят как
калиброванные шумные наблюдения, а не как отдельные чёрные ящики.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import diags
from scipy.sparse.linalg import spsolve

from benchmark import load_bundle


ROOT = Path(__file__).resolve().parents[1]
WORK = Path(r'A:\cosmo_autogluon')
SENSORS = ('s2', 'landsat', 'modis')
TEST_RATE = .15


@dataclass(frozen=True)
class Config:
    name: str
    primary_weight: float
    raw_weight: float
    level_penalty: float
    slope_penalty: float


CONFIGS = (
    # Предел local-linear state без содержательного seasonal prior.
    Config('state_linear_limit', 1_000., 0., .0001, 1.0),
    # Мягкое притяжение к climatology; гладкость относится к x, не к x-c.
    Config('state_seasonal', 80., 0., .015, 1.0),
    Config('state_fused_light', 80., .35, .015, 1.0),
)


def key_set(frame: pd.DataFrame) -> set[tuple[str, pd.Timestamp]]:
    return set(zip(frame['anon_polygon_id'].astype(str), frame['date'], strict=True))


def testlike_query(train: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Маскирует 15% реальных событий в каждом поле, не создавая второй слой gaps."""
    known = train.loc[train['primary_ndvi'].notna()].copy()
    rng = np.random.default_rng(seed)
    picked: list[np.ndarray] = []
    for _, group in known.groupby('anon_polygon_id', sort=False):
        count = max(1, round(len(group) * TEST_RATE))
        picked.append(rng.choice(group.index.to_numpy(), size=count, replace=False))
    return train.loc[np.sort(np.concatenate(picked))].copy().reset_index(drop=True)


def private_query(private: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Повторяет ровно старую private-маску, исключительно для сравнения с v5."""
    known = private.loc[(~private['is_synthetic_gap']) & private['primary_ndvi'].notna()]
    rng = np.random.default_rng(seed)
    selected = rng.choice(known.index.to_numpy(), size=round(len(known) * TEST_RATE), replace=False)
    return private.loc[np.sort(selected)].copy().reset_index(drop=True)


def calibrated_offsets(frame: pd.DataFrame, masked: set[tuple[str, pd.Timestamp]]) -> dict[str, float]:
    """Robust additive calibration raw sensor NDVI -> cascade primary NDVI."""
    keys = pd.MultiIndex.from_frame(frame[['anon_polygon_id', 'date']])
    hidden = keys.isin(pd.MultiIndex.from_tuples(masked, names=['anon_polygon_id', 'date']))
    usable = frame['primary_ndvi'].notna().to_numpy() & ~hidden
    offsets: dict[str, float] = {}
    for sensor in SENSORS:
        difference = (
            frame.loc[usable, 'primary_ndvi'] - frame.loc[usable, f'{sensor}_ndvi']
        ).dropna()
        offsets[sensor] = float(difference.median()) if len(difference) else 0.
    return offsets


def linear_primary(frame: pd.DataFrame, query: pd.DataFrame, masked: set[tuple[str, pd.Timestamp]]) -> np.ndarray:
    """Контроль: линейная интерполяция только по доступным cascade targets."""
    result = np.full(len(query), np.nan)
    for polygon, positions in query.groupby('anon_polygon_id', sort=False).indices.items():
        part = frame.loc[frame['anon_polygon_id'].eq(polygon)].sort_values('date')
        keys = list(zip(part['anon_polygon_id'].astype(str), part['date'], strict=True))
        observed = part['primary_ndvi'].notna().to_numpy() & ~np.fromiter(
            (key in masked for key in keys), dtype=bool, count=len(part)
        )
        days = (part.loc[observed, 'date'] - pd.Timestamp('2010-01-01')).dt.days.to_numpy(float)
        values = part.loc[observed, 'primary_ndvi'].to_numpy(float)
        target_days = (query.iloc[positions]['date'] - pd.Timestamp('2010-01-01')).dt.days.to_numpy(float)
        result[positions] = np.interp(target_days, days, values)
    return result


def state_prediction(
    frame: pd.DataFrame,
    query: pd.DataFrame,
    masked: set[tuple[str, pd.Timestamp]],
    config: Config,
) -> np.ndarray:
    """Kalman-equivalent batch smoother для всех query без доступа к их event values."""
    offsets = calibrated_offsets(frame, masked)
    prediction = np.full(len(query), np.nan)
    epoch = pd.Timestamp('2010-01-01')
    for polygon, positions in query.groupby('anon_polygon_id', sort=False).indices.items():
        part = frame.loc[frame['anon_polygon_id'].eq(polygon)].sort_values('date').reset_index(drop=True)
        dates = part['date']
        event_keys = list(zip(part['anon_polygon_id'].astype(str), dates, strict=True))
        hidden = np.fromiter((key in masked for key in event_keys), dtype=bool, count=len(part))
        primary = part['primary_ndvi'].to_numpy(float)
        climatology = part['ndvi_climatology_mean'].to_numpy(float)
        fallback = float(np.nanmedian(primary)) if np.isfinite(primary).any() else .35
        climatology = np.where(np.isfinite(climatology), climatology, fallback)
        n = len(part)
        diagonal = np.full(n, config.level_penalty)
        rhs = config.level_penalty * climatology
        primary_ok = np.isfinite(primary) & ~hidden
        diagonal[primary_ok] += config.primary_weight
        rhs[primary_ok] += config.primary_weight * primary[primary_ok]
        if config.raw_weight:
            for sensor in SENSORS:
                raw = part[f'{sensor}_ndvi'].to_numpy(float)
                raw_ok = np.isfinite(raw) & ~hidden
                diagonal[raw_ok] += config.raw_weight
                rhs[raw_ok] += config.raw_weight * (raw[raw_ok] + offsets[sensor])
        if n > 1 and config.slope_penalty:
            difference = diags([-np.ones(n - 1), np.ones(n - 1)], [0, 1], shape=(n - 1, n))
            laplacian = difference.T @ difference
            matrix = diags(diagonal) + config.slope_penalty * laplacian
        else:
            matrix = diags(diagonal)
        latent = np.asarray(spsolve(matrix.tocsc(), rhs), dtype=float)
        index_by_date = {date: index for index, date in enumerate(dates)}
        for position in positions:
            prediction[position] = latent[index_by_date[query.iloc[position].date]]
    return np.clip(prediction, -.1, .95)


def rmse(target: np.ndarray, prediction: np.ndarray) -> float:
    return float(np.sqrt(np.mean((target - prediction) ** 2)))


def latest_sequence(seed: int) -> Path:
    candidates = sorted(
        (WORK / 'results').glob(f'multitask_sequence_{seed}_*'),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f'Нет v5 diagnostics для seed={seed}')
    return candidates[-1]


def evaluate(seed: int, private_mode: bool) -> tuple[dict[str, object], pd.DataFrame]:
    bundle = load_bundle(ROOT)
    query = private_query(bundle.private, seed) if private_mode else testlike_query(bundle.train, seed)
    masked = key_set(query)
    # ``combined`` остаётся допустимым трансдуктивным контекстом; query event удалён целиком.
    context = bundle.combined
    output = query[['anon_polygon_id', 'date', 'primary_ndvi']].rename(columns={'primary_ndvi': 'target'}).copy()
    output['linear_primary'] = linear_primary(context, query, masked)
    for config in CONFIGS:
        output[config.name] = state_prediction(context, query, masked, config)
    target = output['target'].to_numpy(float)
    scores = {column: rmse(target, output[column].to_numpy(float)) for column in output.columns[3:]}
    metadata: dict[str, object] = {
        'seed': seed,
        'protocol': (
            'private auxiliary mask; intentionally denser than final test'
            if private_mode
            else '15% mask inside original train fields; no pre-existing hidden primary labels there'
        ),
        'rows': len(output),
        'scores': scores,
        'selected': min(scores, key=scores.get),
    }
    if private_mode:
        sequence = pd.read_parquet(latest_sequence(seed) / 'predictions.parquet')
        if not output[['anon_polygon_id', 'date']].equals(sequence[['anon_polygon_id', 'date']]):
            raise ValueError('State-space и v5 validation имеют разные ключи')
        output['v5'] = .60 * sequence['current_v4'].to_numpy(float) + .40 * sequence['candidate'].to_numpy(float)
        selected = output['state_linear_limit'].to_numpy(float)
        target = output['target'].to_numpy(float)
        metadata['scores']['v5'] = rmse(target, output['v5'].to_numpy(float))
        metadata['state_v5_error_correlation'] = float(
            np.corrcoef(target - selected, target - output['v5'].to_numpy(float))[0, 1]
        )
        metadata['v5_state_blends'] = {
            str(weight): rmse(target, (1. - weight) * output['v5'].to_numpy(float) + weight * selected)
            for weight in (.05, .10, .20)
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
    result_dir = WORK / 'results' / f'state_space_{label}_{args.seed}_{time.strftime("%Y%m%d_%H%M%S")}'
    result_dir.mkdir(parents=True, exist_ok=True)
    output.to_parquet(result_dir / 'predictions.parquet', index=False)
    (result_dir / 'metrics.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)
    print(result_dir, flush=True)


if __name__ == '__main__':
    main()
