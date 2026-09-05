from __future__ import annotations

import argparse
import json
import math
import time
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from lightgbm import LGBMRegressor
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import GroupKFold


RANDOM_SEEDS = (2026, 2027, 2028, 2029, 2030)
SENSOR_INDEX_COLUMNS = (
    's2_ndvi',
    's2_evi',
    's2_ndwi',
    'landsat_ndvi',
    'landsat_evi',
    'landsat_ndwi',
    'modis_ndvi',
    'modis_evi',
)
SENSOR_NDVI_COLUMNS = {
    's2': 's2_ndvi',
    'landsat': 'landsat_ndvi',
    'modis': 'modis_ndvi',
}
DYNAMIC_COLUMNS = (
    's2_ndvi',
    's2_evi',
    's2_ndwi',
    'landsat_ndvi',
    'landsat_evi',
    'landsat_ndwi',
    'modis_ndvi',
    'modis_evi',
    'era5_temp_c',
    'era5_precip_mm',
    'primary_ndvi',
    'ndvi_climatology_mean',
    'ndvi_climatology_std',
)


@dataclass(frozen=True)
class DatasetBundle:
    train: pd.DataFrame
    private: pd.DataFrame
    combined: pd.DataFrame
    key_to_index: dict[tuple[str, pd.Timestamp], int]
    peer_map: dict[str, list[tuple[str, float]]]
    weather_cluster: dict[str, int]


def gap_score(rmse: float) -> float:
    """Переводит RMSE в конкурсный GapScore."""
    return round(30.0 * max(0.0, 1.0 - rmse / 0.10), 2)


def source_labels(frame: pd.DataFrame) -> np.ndarray:
    """Восстанавливает источник primary_ndvi согласно каскаду организаторов."""
    return np.select(
        [
            frame['s2_ndvi'].notna(),
            frame['landsat_ndvi'].notna(),
            frame['modis_ndvi'].notna(),
        ],
        ['s2', 'landsat', 'modis'],
        default='none',
    )


def load_bundle(root: Path) -> DatasetBundle:
    """Загружает train/private и строит разрешённый трансдуктивный контекст."""
    with zipfile.ZipFile(root / 'doc-1788536686.zip') as archive:
        train = pd.read_csv(
            archive.open('train_dataset.csv'),
            parse_dates=['date'],
        )
    private = pd.read_csv(root / 'doc-1788536731.csv', parse_dates=['date'])

    train = train.copy()
    private = private.copy()
    train['source'] = source_labels(train)
    private['source'] = source_labels(private)
    private.loc[private['is_synthetic_gap'], 'source'] = 'hidden'

    common_columns = [
        'anon_polygon_id',
        'date',
        'primary_ndvi',
        'ndvi_climatology_mean',
        'ndvi_climatology_std',
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
        (polygon, date): index
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


def build_weather_clusters(frame: pd.DataFrame, n_clusters: int = 12) -> dict[str, int]:
    """Группирует полигоны по корреляции температурных рядов ERA5."""
    pivot = frame.pivot(index='date', columns='anon_polygon_id', values='era5_temp_c')
    corr = pivot.corr(min_periods=30).fillna(0.0).clip(-1.0, 1.0)
    np.fill_diagonal(corr.values, 1.0)
    distance = (1.0 - corr).clip(0.0, 2.0)
    model = AgglomerativeClustering(
        n_clusters=min(n_clusters, len(corr)),
        metric='precomputed',
        linkage='average',
    )
    labels = model.fit_predict(distance)
    return dict(zip(corr.index.astype(str), labels.astype(int), strict=True))


def build_peer_map(
    frame: pd.DataFrame,
    top_k: int = 8,
) -> dict[str, list[tuple[str, float]]]:
    """Находит поля с наиболее похожей синхронной динамикой NDVI."""
    pivot = frame.pivot(index='date', columns='anon_polygon_id', values='primary_ndvi')
    corr = pivot.corr(min_periods=30)
    result: dict[str, list[tuple[str, float]]] = {}
    for polygon in corr.columns:
        peers = corr[polygon].drop(index=polygon).dropna().sort_values(ascending=False)
        peers = peers[peers > 0.20].head(top_k)
        result[str(polygon)] = [(str(peer), float(value)) for peer, value in peers.items()]
    return result


def exact_mask_indices(
    frame: pd.DataFrame,
    seed: int,
    fraction: float = 0.15,
) -> np.ndarray:
    """Выбирает ровно заданную долю наблюдавшихся target для synthetic gaps."""
    candidates = frame.index[frame['primary_ndvi'].notna()].to_numpy()
    count = round(len(candidates) * fraction)
    generator = np.random.default_rng(seed)
    return np.sort(generator.choice(candidates, size=count, replace=False))


def _lookup_stat(table: pd.DataFrame, key: object, column: str) -> float:
    try:
        value = table.loc[key, column]
    except KeyError:
        return math.nan
    return float(value) if pd.notna(value) else math.nan


def _safe_weighted(values: list[float], weights: list[float]) -> float:
    if not values:
        return math.nan
    values_array = np.asarray(values, dtype=float)
    weights_array = np.asarray(weights, dtype=float)
    denominator = weights_array.sum()
    if denominator <= 0:
        return float(np.mean(values_array))
    return float(np.dot(values_array, weights_array) / denominator)


def _low_rank_predictions(
    frame: pd.DataFrame,
    known_target: np.ndarray,
    query_indices: np.ndarray,
    ranks: Iterable[int] = (12, 32),
    iterations: int = 8,
) -> dict[int, np.ndarray]:
    """Выполняет мягкое низкоранговое восстановление date × polygon."""
    dates = pd.Index(sorted(frame['date'].unique()))
    polygons = pd.Index(sorted(frame['anon_polygon_id'].unique()))
    date_index = {value: index for index, value in enumerate(dates)}
    polygon_index = {value: index for index, value in enumerate(polygons)}
    matrix = np.full((len(dates), len(polygons)), np.nan, dtype=float)

    observed_rows = frame.loc[known_target, ['date', 'anon_polygon_id', 'primary_ndvi']]
    for row in observed_rows.itertuples(index=False):
        matrix[date_index[row.date], polygon_index[row.anon_polygon_id]] = row.primary_ndvi
    observed = np.isfinite(matrix)
    date_days = dates.astype('int64').to_numpy(dtype=float) / 86_400_000_000_000.0

    initial = np.empty_like(matrix)
    for column in range(matrix.shape[1]):
        present = observed[:, column]
        if present.sum() == 0:
            initial[:, column] = np.nanmedian(matrix)
            continue
        x = date_days[present]
        y = matrix[present, column]
        insertion = np.searchsorted(x, date_days)
        left = np.clip(insertion - 1, 0, len(x) - 1)
        right = np.clip(insertion, 0, len(x) - 1)
        initial[:, column] = (y[left] + y[right]) / 2.0

    output: dict[int, np.ndarray] = {}
    query_rows = np.array([date_index[value] for value in frame.loc[query_indices, 'date']])
    query_columns = np.array(
        [polygon_index[value] for value in frame.loc[query_indices, 'anon_polygon_id']]
    )
    for rank in ranks:
        reconstruction = initial.copy()
        for _ in range(iterations):
            clipped = np.clip(reconstruction, -0.20, 1.00)
            u, singular, vt = np.linalg.svd(clipped, full_matrices=False)
            estimate = (u[:, :rank] * singular[:rank]) @ vt[:rank]
            reconstruction[~observed] = estimate[~observed]
            reconstruction[observed] = matrix[observed]
        output[rank] = reconstruction[query_rows, query_columns]
    return output


def build_features(
    bundle: DatasetBundle,
    query: pd.DataFrame,
    masked_keys: set[tuple[str, pd.Timestamp]],
    label: str,
) -> pd.DataFrame:
    """Формирует признаки так, будто динамические поля query полностью скрыты."""
    started = time.perf_counter()
    frame = bundle.combined
    masked = np.zeros(len(frame), dtype=bool)
    for key in masked_keys:
        index = bundle.key_to_index.get(key)
        if index is not None:
            masked[index] = True
    known_target = frame['primary_ndvi'].notna().to_numpy() & ~masked

    by_polygon: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
    by_polygon_year: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}
    dynamic_interpolation: dict[str, dict[str, np.ndarray]] = {}
    raw_series_by_polygon: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]] = {}
    row_location: dict[str, dict[int, int]] = {}
    residual_records: list[tuple[pd.Timestamp, str, str, int, float]] = []
    sensor_residual_records: list[tuple[pd.Timestamp, str, int, float]] = []

    for polygon, raw_indices in frame.groupby('anon_polygon_id').groups.items():
        indices = np.asarray(list(raw_indices), dtype=int)
        present_indices = indices[known_target[indices]]
        days = frame.loc[present_indices, 'day'].to_numpy(dtype=float)
        values = frame.loc[present_indices, 'primary_ndvi'].to_numpy(dtype=float)
        order = np.argsort(days)
        present_indices = present_indices[order]
        days = days[order]
        values = values[order]
        sources = frame.loc[present_indices, 'source'].to_numpy(dtype=str)
        by_polygon[str(polygon)] = (days, values, present_indices, sources)

        raw_series_by_polygon[str(polygon)] = {}
        for column in SENSOR_INDEX_COLUMNS:
            available_indices = indices[
                frame.loc[indices, column].notna().to_numpy() & ~masked[indices]
            ]
            raw_days = frame.loc[available_indices, 'day'].to_numpy(dtype=float)
            raw_values = frame.loc[available_indices, column].to_numpy(dtype=float)
            raw_order = np.argsort(raw_days)
            raw_days = raw_days[raw_order]
            raw_values = raw_values[raw_order]
            available_indices = available_indices[raw_order]
            raw_series_by_polygon[str(polygon)][column] = (raw_days, raw_values)
            if column in SENSOR_NDVI_COLUMNS.values() and len(raw_values) >= 3:
                sensor_name = column.removesuffix('_ndvi')
                raw_residual = raw_values[1:-1] - (raw_values[:-2] + raw_values[2:]) / 2.0
                for raw_index, residual_value in zip(
                    available_indices[1:-1],
                    raw_residual,
                    strict=True,
                ):
                    sensor_residual_records.append(
                        (
                            frame.at[raw_index, 'date'],
                            sensor_name,
                            bundle.weather_cluster[str(polygon)],
                            float(residual_value),
                        )
                    )

        if len(values) >= 3:
            residual = np.full(len(values), np.nan)
            residual[1:-1] = values[1:-1] - (values[:-2] + values[2:]) / 2.0
            for position in range(1, len(values) - 1):
                index = present_indices[position]
                residual_records.append(
                    (
                        frame.at[index, 'date'],
                        str(polygon),
                        str(frame.at[index, 'crop_type']),
                        bundle.weather_cluster[str(polygon)],
                        float(residual[position]),
                    )
                )

        for year, year_indices_raw in frame.loc[indices].groupby('year_calc').groups.items():
            year_indices = np.asarray(list(year_indices_raw), dtype=int)
            year_indices = year_indices[known_target[year_indices]]
            year_days = frame.loc[year_indices, 'doy_calc'].to_numpy(dtype=float)
            year_values = frame.loc[year_indices, 'primary_ndvi'].to_numpy(dtype=float)
            year_order = np.argsort(year_days)
            by_polygon_year[(str(polygon), int(year))] = (
                year_days[year_order],
                year_values[year_order],
            )

        query_days = frame.loc[indices, 'day'].to_numpy(dtype=float)
        interpolated: dict[str, np.ndarray] = {}
        for column in ('ndvi_climatology_mean', 'ndvi_climatology_std', 'era5_temp_c', 'era5_precip_mm'):
            available = frame.loc[indices, column].notna().to_numpy() & ~masked[indices]
            if available.sum() >= 2:
                interpolated[column] = np.interp(
                    query_days,
                    frame.loc[indices[available], 'day'].to_numpy(dtype=float),
                    frame.loc[indices[available], column].to_numpy(dtype=float),
                )
            elif available.sum() == 1:
                interpolated[column] = np.full(
                    len(indices),
                    float(frame.loc[indices[available], column].iloc[0]),
                )
            else:
                interpolated[column] = np.full(len(indices), np.nan)
        dynamic_interpolation[str(polygon)] = interpolated
        row_location[str(polygon)] = {index: position for position, index in enumerate(indices)}

    residual_frame = pd.DataFrame(
        residual_records,
        columns=['date', 'anon_polygon_id', 'crop_type', 'weather_cluster', 'residual'],
    )
    date_residual = residual_frame.groupby('date')['residual'].agg(['mean', 'median', 'std', 'count'])
    crop_date_residual = residual_frame.groupby(['crop_type', 'date'])['residual'].agg(
        ['mean', 'median', 'std', 'count']
    )
    cluster_date_residual = residual_frame.groupby(['weather_cluster', 'date'])['residual'].agg(
        ['mean', 'median', 'std', 'count']
    )
    residual_pivot = residual_frame.pivot(index='date', columns='anon_polygon_id', values='residual')
    sensor_residual_frame = pd.DataFrame(
        sensor_residual_records,
        columns=['date', 'sensor', 'weather_cluster', 'residual'],
    )
    sensor_date_residual = sensor_residual_frame.groupby(['sensor', 'date'])['residual'].agg(
        ['mean', 'median', 'std', 'count']
    )
    sensor_cluster_date_residual = sensor_residual_frame.groupby(
        ['sensor', 'weather_cluster', 'date']
    )['residual'].agg(['mean', 'median', 'std', 'count'])

    known_frame = frame.loc[known_target]
    date_primary = known_frame.groupby('date')['primary_ndvi'].agg(['mean', 'median', 'std', 'count'])
    crop_date_primary = known_frame.groupby(['crop_type', 'date'])['primary_ndvi'].agg(
        ['mean', 'median', 'std', 'count']
    )
    sensor_counts = frame.loc[~masked].groupby('date')[
        ['s2_ndvi', 'landsat_ndvi', 'modis_ndvi']
    ].count()

    query_indices = np.array(
        [bundle.key_to_index[(polygon, date)] for polygon, date in zip(query['anon_polygon_id'], query['date'], strict=True)],
        dtype=int,
    )
    low_rank = _low_rank_predictions(frame, known_target, query_indices)

    features: list[dict[str, object]] = []
    all_years_by_polygon = {
        str(polygon): sorted(group['year_calc'].unique())
        for polygon, group in frame.groupby('anon_polygon_id')
    }

    for query_position, row in enumerate(query.itertuples(index=False)):
        polygon = str(row.anon_polygon_id)
        date = pd.Timestamp(row.date)
        day = int((date - pd.Timestamp('2010-01-01')).days)
        year = date.year
        doy = date.dayofyear
        crop = str(row.crop_type)
        cluster = bundle.weather_cluster[polygon]
        days, values, known_indices, known_sources = by_polygon[polygon]
        insertion = int(np.searchsorted(days, day))
        item: dict[str, object] = {
            'year': year,
            'doy': doy,
            'sin_1': math.sin(2.0 * math.pi * doy / 365.25),
            'cos_1': math.cos(2.0 * math.pi * doy / 365.25),
            'sin_2': math.sin(4.0 * math.pi * doy / 365.25),
            'cos_2': math.cos(4.0 * math.pi * doy / 365.25),
            'crop_type': crop,
            'weather_cluster': cluster,
        }

        for offset in range(1, 6):
            left = insertion - offset
            right = insertion + offset - 1
            item[f'prev_y_{offset}'] = values[left] if left >= 0 else math.nan
            item[f'prev_dt_{offset}'] = day - days[left] if left >= 0 else math.nan
            item[f'next_y_{offset}'] = values[right] if right < len(days) else math.nan
            item[f'next_dt_{offset}'] = days[right] - day if right < len(days) else math.nan

        if 0 < insertion < len(days):
            left = insertion - 1
            right = insertion
            left_distance = day - days[left]
            right_distance = days[right] - day
            span = left_distance + right_distance
            item['baseline_avg'] = (values[left] + values[right]) / 2.0
            item['baseline_linear'] = (
                values[left] * right_distance + values[right] * left_distance
            ) / span
            item['baseline_nearest'] = values[left] if left_distance <= right_distance else values[right]
            item['local_slope'] = (values[right] - values[left]) / span
            item['gap_span'] = span
            item['gap_asymmetry'] = (left_distance - right_distance) / span
            item['prev_source_code'] = {'s2': 0, 'landsat': 1, 'modis': 2}.get(known_sources[left], 3)
            item['next_source_code'] = {'s2': 0, 'landsat': 1, 'modis': 2}.get(known_sources[right], 3)
        else:
            fallback = values[0] if insertion == 0 else values[-1]
            item.update(
                baseline_avg=fallback,
                baseline_linear=fallback,
                baseline_nearest=fallback,
                local_slope=0.0,
                gap_span=999.0,
                gap_asymmetry=0.0,
                prev_source_code=3,
                next_source_code=3,
            )

        local_start = max(0, insertion - 4)
        local_end = min(len(values), insertion + 4)
        local_values = values[local_start:local_end]
        item['local_mean'] = float(np.mean(local_values))
        item['local_median'] = float(np.median(local_values))
        item['local_std'] = float(np.std(local_values))
        item['field_mean'] = float(np.mean(values))
        item['field_std'] = float(np.std(values))

        # Сенсорно-раздельные временные ряды используют все доступные измерения
        # сенсора, включая строки, где primary_ndvi был выбран из другого источника.
        for column, (raw_days, raw_values) in raw_series_by_polygon[polygon].items():
            prefix = f'raw_{column}'
            if len(raw_values) == 0:
                item[f'{prefix}_avg'] = math.nan
                item[f'{prefix}_linear'] = math.nan
                item[f'{prefix}_nearest'] = math.nan
                item[f'{prefix}_span'] = math.nan
                continue
            raw_insertion = int(np.searchsorted(raw_days, day))
            raw_left = max(0, raw_insertion - 1)
            raw_right = min(len(raw_days) - 1, raw_insertion)
            raw_left_distance = day - raw_days[raw_left]
            raw_right_distance = raw_days[raw_right] - day
            raw_span = raw_left_distance + raw_right_distance
            item[f'{prefix}_avg'] = (raw_values[raw_left] + raw_values[raw_right]) / 2.0
            item[f'{prefix}_nearest'] = (
                raw_values[raw_left]
                if raw_left_distance <= raw_right_distance
                else raw_values[raw_right]
            )
            item[f'{prefix}_linear'] = (
                raw_values[raw_left]
                if raw_span <= 0
                else (
                    raw_values[raw_left] * raw_right_distance
                    + raw_values[raw_right] * raw_left_distance
                )
                / raw_span
            )
            item[f'{prefix}_span'] = raw_span

        history: list[float] = []
        for historic_year in all_years_by_polygon[polygon]:
            if int(historic_year) == year:
                continue
            historic_days, historic_values = by_polygon_year[(polygon, int(historic_year))]
            if (
                len(historic_days) >= 2
                and doy >= historic_days.min() - 10
                and doy <= historic_days.max() + 10
            ):
                history.append(float(np.interp(doy, historic_days, historic_values)))
        if history:
            item['history_mean'] = float(np.mean(history))
            item['history_median'] = float(np.median(history))
            item['history_std'] = float(np.std(history))
            item['history_q25'] = float(np.quantile(history, 0.25))
            item['history_q75'] = float(np.quantile(history, 0.75))
            item['history_count'] = len(history)
        else:
            for column in (
                'history_mean',
                'history_median',
                'history_std',
                'history_q25',
                'history_q75',
            ):
                item[column] = math.nan
            item['history_count'] = 0

        combined_index = query_indices[query_position]
        dynamic_position = row_location[polygon][combined_index]
        item['clim_mean_interp'] = dynamic_interpolation[polygon]['ndvi_climatology_mean'][dynamic_position]
        item['clim_std_interp'] = dynamic_interpolation[polygon]['ndvi_climatology_std'][dynamic_position]
        item['weather_temp_interp'] = dynamic_interpolation[polygon]['era5_temp_c'][dynamic_position]
        item['weather_precip_interp'] = dynamic_interpolation[polygon]['era5_precip_mm'][dynamic_position]

        for prefix, table, key in (
            ('date_resid', date_residual, date),
            ('cropdate_resid', crop_date_residual, (crop, date)),
            ('clusterdate_resid', cluster_date_residual, (cluster, date)),
            ('date_primary', date_primary, date),
            ('cropdate_primary', crop_date_primary, (crop, date)),
        ):
            for statistic in ('mean', 'median', 'std', 'count'):
                item[f'{prefix}_{statistic}'] = _lookup_stat(table, key, statistic)

        peer_values: list[float] = []
        peer_weights: list[float] = []
        if date in residual_pivot.index:
            row_residuals = residual_pivot.loc[date]
            for peer, correlation in bundle.peer_map.get(polygon, []):
                if peer in row_residuals.index and pd.notna(row_residuals[peer]):
                    peer_values.append(float(row_residuals[peer]))
                    peer_weights.append(max(correlation, 0.0) ** 2)
        item['peer_resid_weighted'] = _safe_weighted(peer_values, peer_weights)
        item['peer_resid_median'] = float(np.median(peer_values)) if peer_values else math.nan
        item['peer_count'] = len(peer_values)

        for sensor in ('s2_ndvi', 'landsat_ndvi', 'modis_ndvi'):
            item[f'sensor_count_{sensor}'] = _lookup_stat(sensor_counts, date, sensor)
        sensor_total = sum(
            float(item[f'sensor_count_{sensor}'])
            for sensor in ('s2_ndvi', 'landsat_ndvi', 'modis_ndvi')
            if pd.notna(item[f'sensor_count_{sensor}'])
        )
        for sensor in ('s2_ndvi', 'landsat_ndvi', 'modis_ndvi'):
            count = item[f'sensor_count_{sensor}']
            item[f'sensor_share_{sensor}'] = float(count) / sensor_total if sensor_total > 0 else 0.0

        for sensor, column in SENSOR_NDVI_COLUMNS.items():
            date_key = (sensor, date)
            cluster_key = (sensor, cluster, date)
            for statistic in ('mean', 'median', 'std', 'count'):
                item[f'{sensor}_date_resid_{statistic}'] = _lookup_stat(
                    sensor_date_residual,
                    date_key,
                    statistic,
                )
                item[f'{sensor}_clusterdate_resid_{statistic}'] = _lookup_stat(
                    sensor_cluster_date_residual,
                    cluster_key,
                    statistic,
                )
            raw_average = item[f'raw_{column}_avg']
            date_correction = item[f'{sensor}_date_resid_mean']
            item[f'{sensor}_corrected_expert'] = (
                float(raw_average) + float(date_correction)
                if pd.notna(raw_average) and pd.notna(date_correction)
                else raw_average
            )

        item['lowrank_12'] = float(low_rank[12][query_position])
        item['lowrank_32'] = float(low_rank[32][query_position])
        item['target'] = float(row.primary_ndvi) if pd.notna(row.primary_ndvi) else math.nan
        item['target_source'] = str(row.source)
        item['anon_polygon_id'] = polygon
        item['date'] = date
        item['validation_label'] = label
        features.append(item)

    result = pd.DataFrame(features)
    elapsed = time.perf_counter() - started
    print(f'Признаки {label}: {len(result):,} строк, {elapsed:.1f} с', flush=True)
    return result


def prepare_train_feature_sets(bundle: DatasetBundle, seeds: Iterable[int]) -> dict[int, pd.DataFrame]:
    """Создаёт несколько независимых competition-like масок на train."""
    result: dict[int, pd.DataFrame] = {}
    for seed in seeds:
        indices = exact_mask_indices(bundle.train, seed)
        query = bundle.train.loc[indices].copy()
        masked_keys = set(zip(query['anon_polygon_id'], query['date'], strict=True))
        result[seed] = build_features(bundle, query, masked_keys, f'train_seed_{seed}')
    return result


def prepare_private_validation(bundle: DatasetBundle, seed: int = 3030) -> pd.DataFrame:
    """Создаёт консервативную дополнительную валидацию на известных private-точках."""
    known = bundle.private[
        (~bundle.private['is_synthetic_gap']) & bundle.private['primary_ndvi'].notna()
    ]
    generator = np.random.default_rng(seed)
    count = round(len(known) * 0.15)
    selected = np.sort(generator.choice(known.index.to_numpy(), size=count, replace=False))
    query = bundle.private.loc[selected].copy()
    masked_keys = set(zip(query['anon_polygon_id'], query['date'], strict=True))
    output = build_features(bundle, query, masked_keys, f'private_seed_{seed}')
    train_ids = set(bundle.train['anon_polygon_id'])
    output['regime'] = np.where(output['anon_polygon_id'].isin(train_ids), 'seen_id', 'new_id')
    return output


def _feature_columns(frame: pd.DataFrame) -> list[str]:
    metadata = {
        'target',
        'target_source',
        'anon_polygon_id',
        'date',
        'validation_label',
        'regime',
    }
    return [column for column in frame.columns if column not in metadata]


def _fit_catboost(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    columns: list[str],
    iterations: int,
    seed: int,
) -> tuple[np.ndarray, pd.Series]:
    x_train = train[columns].copy()
    x_validation = validation[columns].copy()
    categorical = [column for column in ('crop_type',) if column in columns]
    for column in categorical:
        x_train[column] = x_train[column].fillna('unknown').astype(str)
        x_validation[column] = x_validation[column].fillna('unknown').astype(str)
    categorical_indices = [x_train.columns.get_loc(column) for column in categorical]
    model = CatBoostRegressor(
        iterations=iterations,
        depth=8,
        learning_rate=0.04,
        loss_function='RMSE',
        l2_leaf_reg=8,
        random_seed=seed,
        verbose=False,
        allow_writing_files=False,
        thread_count=-1,
    )
    model.fit(x_train, train['target'], cat_features=categorical_indices)
    importance = pd.Series(model.feature_importances_, index=columns)
    return model.predict(x_validation), importance


def _fit_lightgbm(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    columns: list[str],
    iterations: int,
    seed: int,
) -> np.ndarray:
    x_train = train[columns].copy()
    x_validation = validation[columns].copy()
    if 'crop_type' in columns:
        categories = sorted(set(x_train['crop_type'].astype(str)) | set(x_validation['crop_type'].astype(str)))
        mapping = {value: index for index, value in enumerate(categories)}
        x_train['crop_type'] = x_train['crop_type'].astype(str).map(mapping).fillna(-1)
        x_validation['crop_type'] = x_validation['crop_type'].astype(str).map(mapping).fillna(-1)
    model = LGBMRegressor(
        n_estimators=iterations,
        learning_rate=0.03,
        num_leaves=31,
        max_depth=-1,
        min_child_samples=30,
        subsample=0.90,
        colsample_bytree=0.85,
        reg_lambda=5.0,
        random_state=seed,
        n_jobs=-1,
        verbosity=-1,
    )
    model.fit(x_train, train['target'])
    return model.predict(x_validation)


def _fit_sensor_bias_model(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    columns: list[str],
    seed: int,
) -> np.ndarray:
    """Оценивает источник пропуска и применяет source-specific bias к baseline."""
    x_train = train[columns].copy()
    x_validation = validation[columns].copy()
    categorical = [column for column in ('crop_type',) if column in columns]
    for column in categorical:
        x_train[column] = x_train[column].fillna('unknown').astype(str)
        x_validation[column] = x_validation[column].fillna('unknown').astype(str)
    categorical_indices = [x_train.columns.get_loc(column) for column in categorical]
    classifier = CatBoostClassifier(
        iterations=350,
        depth=6,
        learning_rate=0.05,
        loss_function='MultiClass',
        random_seed=seed,
        verbose=False,
        allow_writing_files=False,
        thread_count=-1,
    )
    classifier.fit(x_train, train['target_source'], cat_features=categorical_indices)
    probabilities = classifier.predict_proba(x_validation)
    biases = (train['target'] - train['baseline_avg']).groupby(train['target_source']).mean()
    expected_bias = np.zeros(len(validation), dtype=float)
    for class_index, source in enumerate(classifier.classes_):
        expected_bias += probabilities[:, class_index] * float(biases.get(source, 0.0))
    return validation['baseline_avg'].to_numpy() + expected_bias


def run_grouped_benchmark(
    feature_sets: dict[int, pd.DataFrame],
    folds: int,
    iterations: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Считает OOF по целым полигонам для каждого synthetic-gap seed."""
    seeds = sorted(feature_sets)
    combined = pd.concat(feature_sets.values(), ignore_index=True)
    columns = _feature_columns(combined)
    groups = sorted(combined['anon_polygon_id'].unique())
    group_frame = pd.DataFrame({'polygon': groups})
    group_frame['dummy'] = 0
    splitter = GroupKFold(n_splits=folds)
    polygon_folds: list[set[str]] = []
    for _, validation_indices in splitter.split(
        group_frame,
        groups=group_frame['polygon'],
    ):
        polygon_folds.append(set(group_frame.iloc[validation_indices]['polygon']))

    predictions: list[pd.DataFrame] = []
    importances: list[pd.Series] = []
    for seed in seeds:
        evaluation_seed = feature_sets[seed]
        for fold_index, validation_polygons in enumerate(polygon_folds):
            validation = evaluation_seed[
                evaluation_seed['anon_polygon_id'].isin(validation_polygons)
            ].copy()
            train = combined[~combined['anon_polygon_id'].isin(validation_polygons)].copy()
            print(
                f'Модели: seed={seed}, fold={fold_index + 1}/{folds}, '
                f'train={len(train):,}, val={len(validation):,}',
                flush=True,
            )
            cat_prediction, importance = _fit_catboost(
                train,
                validation,
                columns,
                iterations,
                seed + fold_index,
            )
            light_prediction = _fit_lightgbm(
                train,
                validation,
                columns,
                iterations,
                seed + fold_index,
            )
            sensor_prediction = _fit_sensor_bias_model(
                train,
                validation,
                columns,
                seed + fold_index,
            )
            output = validation[
                [
                    'target',
                    'target_source',
                    'anon_polygon_id',
                    'date',
                    'crop_type',
                    'year',
                    'doy',
                    'gap_span',
                    'validation_label',
                ]
            ].copy()
            output['seed'] = seed
            output['fold'] = fold_index
            output['baseline_avg'] = validation['baseline_avg'].to_numpy()
            output['baseline_linear'] = validation['baseline_linear'].to_numpy()
            output['local_median'] = validation['local_median'].to_numpy()
            output['climatology'] = validation['clim_mean_interp'].to_numpy()
            output['lowrank_32'] = validation['lowrank_32'].to_numpy()
            output['peer_corrected'] = (
                validation['baseline_avg'].to_numpy()
                + 0.85 * validation['date_resid_mean'].fillna(0.0).to_numpy()
            )
            output['sensor_bias'] = sensor_prediction
            output['catboost'] = cat_prediction
            output['lightgbm'] = light_prediction
            output['ensemble'] = 0.60 * cat_prediction + 0.40 * light_prediction
            output['ensemble_clip'] = np.clip(output['ensemble'], -0.10, 0.95)
            predictions.append(output)
            importances.append(importance.rename(f'seed_{seed}_fold_{fold_index}'))

    return pd.concat(predictions, ignore_index=True), pd.concat(importances, axis=1)


def run_ablation(
    feature_sets: dict[int, pd.DataFrame],
    seed: int,
    folds: int,
    iterations: int,
) -> pd.DataFrame:
    """Оценивает вклад sensor, cross-field и climate блоков на одном seed."""
    combined = pd.concat(feature_sets.values(), ignore_index=True)
    evaluation = feature_sets[seed]
    full_columns = _feature_columns(combined)
    sensor_columns = [
        column
        for column in full_columns
        if column.startswith('sensor_') or column in {'prev_source_code', 'next_source_code'}
    ]
    cross_columns = [
        column
        for column in full_columns
        if column.startswith(('date_', 'cropdate_', 'clusterdate_', 'peer_', 'lowrank_'))
    ]
    climate_columns = [
        column
        for column in full_columns
        if column.startswith(('history_', 'clim_', 'weather_'))
    ]
    variants = {
        'catboost_full': full_columns,
        'catboost_without_sensor': [column for column in full_columns if column not in sensor_columns],
        'catboost_without_crossfield': [column for column in full_columns if column not in cross_columns],
        'catboost_without_climate_weather': [column for column in full_columns if column not in climate_columns],
        'catboost_local_only': [
            column
            for column in full_columns
            if column not in set(sensor_columns + cross_columns + climate_columns)
        ],
    }

    groups = sorted(combined['anon_polygon_id'].unique())
    group_frame = pd.DataFrame({'polygon': groups})
    splitter = GroupKFold(n_splits=folds)
    records: list[dict[str, object]] = []
    for fold_index, (_, validation_indices) in enumerate(
        splitter.split(group_frame, groups=group_frame['polygon'])
    ):
        validation_polygons = set(group_frame.iloc[validation_indices]['polygon'])
        validation = evaluation[evaluation['anon_polygon_id'].isin(validation_polygons)]
        train = combined[~combined['anon_polygon_id'].isin(validation_polygons)]
        for name, columns in variants.items():
            prediction, _ = _fit_catboost(
                train,
                validation,
                columns,
                max(350, iterations // 2),
                seed + fold_index,
            )
            records.append(
                {
                    'method': name,
                    'fold': fold_index,
                    'n': len(validation),
                    'rmse': mean_squared_error(validation['target'], prediction) ** 0.5,
                }
            )
    return pd.DataFrame(records)


def fit_and_evaluate_private(
    feature_sets: dict[int, pd.DataFrame],
    private_features: pd.DataFrame,
    iterations: int,
) -> pd.DataFrame:
    """Проверяет перенос на известные private-точки, скрытые дополнительной маской."""
    train = pd.concat(feature_sets.values(), ignore_index=True)
    columns = _feature_columns(train)
    cat_prediction, _ = _fit_catboost(train, private_features, columns, iterations, 4040)
    light_prediction = _fit_lightgbm(train, private_features, columns, iterations, 4040)
    output = private_features[
        [
            'target',
            'target_source',
            'anon_polygon_id',
            'date',
            'crop_type',
            'year',
            'doy',
            'gap_span',
            'regime',
        ]
    ].copy()
    output['baseline_avg'] = private_features['baseline_avg'].to_numpy()
    output['peer_corrected'] = (
        private_features['baseline_avg'].to_numpy()
        + 0.85 * private_features['date_resid_mean'].fillna(0.0).to_numpy()
    )
    output['catboost'] = cat_prediction
    output['lightgbm'] = light_prediction
    output['ensemble'] = 0.60 * cat_prediction + 0.40 * light_prediction
    output['ensemble_clip'] = np.clip(output['ensemble'], -0.10, 0.95)
    return output


def metric_table(predictions: pd.DataFrame, group_column: str = 'seed') -> pd.DataFrame:
    """Агрегирует RMSE/MAE и конкурсный балл для всех столбцов прогнозов."""
    metadata = {
        'target',
        'target_source',
        'anon_polygon_id',
        'date',
        'crop_type',
        'year',
        'doy',
        'gap_span',
        'validation_label',
        'seed',
        'fold',
        'regime',
    }
    methods = [column for column in predictions.columns if column not in metadata]
    records: list[dict[str, object]] = []
    for group, group_frame in predictions.groupby(group_column):
        for method in methods:
            valid = group_frame[method].notna()
            truth = group_frame.loc[valid, 'target']
            estimate = group_frame.loc[valid, method]
            rmse = mean_squared_error(truth, estimate) ** 0.5
            records.append(
                {
                    group_column: group,
                    'method': method,
                    'n': int(valid.sum()),
                    'rmse': rmse,
                    'mae': float(np.mean(np.abs(truth - estimate))),
                    'gap_score': gap_score(rmse),
                }
            )
    return pd.DataFrame(records)


def slice_table(predictions: pd.DataFrame, method: str) -> pd.DataFrame:
    """Строит диагностические разрезы финального метода."""
    frame = predictions.copy()
    frame['span_bucket'] = pd.cut(
        frame['gap_span'],
        bins=[0, 2, 4, 7, 14, 30, 10_000],
        labels=['≤2', '3–4', '5–7', '8–14', '15–30', '>30'],
    ).astype(str)
    records: list[dict[str, object]] = []
    for dimension in ('target_source', 'span_bucket', 'year', 'crop_type'):
        for value, group in frame.groupby(dimension):
            rmse = mean_squared_error(group['target'], group[method]) ** 0.5
            records.append(
                {
                    'dimension': dimension,
                    'value': value,
                    'n': len(group),
                    'rmse': rmse,
                    'mae': float(np.mean(np.abs(group['target'] - group[method]))),
                }
            )
    return pd.DataFrame(records)


def dataset_profile(bundle: DatasetBundle) -> dict[str, object]:
    """Возвращает основные проверяемые характеристики соревнования."""
    train = bundle.train
    private = bundle.private
    train_ids = set(train['anon_polygon_id'])
    private_ids = set(private['anon_polygon_id'])
    primary = train['primary_ndvi']
    cascade = train['s2_ndvi'].fillna(train['landsat_ndvi']).fillna(train['modis_ndvi'])
    comparable = primary.notna()
    return {
        'train_rows': len(train),
        'train_polygons': train['anon_polygon_id'].nunique(),
        'train_target_observations': int(primary.notna().sum()),
        'private_rows': len(private),
        'private_polygons': private['anon_polygon_id'].nunique(),
        'private_known_targets': int(private['primary_ndvi'].notna().sum()),
        'private_synthetic_gaps': int(private['is_synthetic_gap'].sum()),
        'overlap_polygons': len(train_ids & private_ids),
        'new_private_polygons': len(private_ids - train_ids),
        'primary_cascade_exact_share': float(
            np.mean(np.isclose(primary[comparable], cascade[comparable], atol=1e-12))
        ),
    }


def write_report(
    output_dir: Path,
    profile: dict[str, object],
    seed_metrics: pd.DataFrame,
    private_metrics: pd.DataFrame,
    ablation: pd.DataFrame,
    slices: pd.DataFrame,
) -> None:
    """Формирует компактный Markdown-отчёт для команды и жюри."""
    summary = (
        seed_metrics.groupby('method')
        .agg(
            rmse_mean=('rmse', 'mean'),
            rmse_std=('rmse', 'std'),
            mae_mean=('mae', 'mean'),
            gap_score_mean=('gap_score', 'mean'),
            seeds=('seed', 'nunique'),
        )
        .sort_values('rmse_mean')
        .reset_index()
    )
    ablation_summary = (
        ablation.groupby('method')
        .apply(
            lambda group: pd.Series(
                {
                    'weighted_rmse': math.sqrt(
                        np.average(group['rmse'] ** 2, weights=group['n'])
                    ),
                    'folds': group['fold'].nunique(),
                }
            ),
            include_groups=False,
        )
        .reset_index()
        .sort_values('weighted_rmse')
    )
    private_summary = private_metrics.sort_values(['regime', 'rmse'])

    def markdown_table(frame: pd.DataFrame, digits: int = 5) -> str:
        shown = frame.copy()
        for column in shown.select_dtypes(include='number').columns:
            shown[column] = shown[column].map(
                lambda value: f'{value:.{digits}f}' if isinstance(value, (float, np.floating)) else value
            )
        return shown.to_markdown(index=False)

    best = summary.iloc[0]
    report = f"""# Технический benchmark восстановления NDVI

## Результат

Лучший метод в grouped-проверке: **{best['method']}**, средний RMSE **{best['rmse_mean']:.5f} ± {best['rmse_std']:.5f}**, ожидаемый GapScore **{best['gap_score_mean']:.2f}**.

Проверка проводилась с synthetic gaps ровно на 15% известных train-точек. Все динамические признаки выбранной строки исключались. Мета-модели оценивались на полигонах, полностью исключённых из их обучения.

## Профиль данных

```json
{json.dumps(profile, ensure_ascii=False, indent=2)}
```

## Grouped cross-validation

{markdown_table(summary)}

## Перенос на дополнительно скрытые private-точки

Эта проверка консервативна: в private уже остаются настоящие 15% synthetic gaps, после чего дополнительно скрывается 15% известных значений.

{markdown_table(private_summary)}

## Абляции CatBoost

{markdown_table(ablation_summary)}

## Диагностические разрезы лучшего ансамбля

{markdown_table(slices.sort_values(['dimension', 'rmse']).head(80))}

## Интерпретация

- `baseline_avg` — среднее ближайших известных значений, соответствующее постановке организаторов.
- `peer_corrected` добавляет синхронный остаток других полей в ту же дату.
- `sensor_bias` сначала оценивает вероятный источник скрытой точки, затем применяет source-specific коррекцию.
- `lowrank_32` восстанавливает матрицу `date × polygon` низкоранговой моделью.
- `catboost` и `lightgbm` объединяют локальную геометрию, сезон, климатологию, сенсорные расписания и межполевые признаки.

## Ограничения

- Значения на private leaderboard неизвестны, поэтому приведённые баллы являются оценкой по локальной валидации.
- Private-validation строже реального сценария, поскольку создаёт дополнительные пропуски поверх уже существующих.
- Гиперпараметры выбраны ограниченным поиском; дальнейший прирост возможен за счёт оптимизации gating и sensor-specific experts.
"""
    (output_dir / 'TECHNICAL_REPORT.md').write_text(report, encoding='utf-8')
    summary.to_csv(output_dir / 'benchmark_summary.csv', index=False, encoding='utf-8')
    ablation_summary.to_csv(output_dir / 'ablation_summary.csv', index=False, encoding='utf-8')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Benchmark восстановления primary_ndvi')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'results')
    parser.add_argument('--seeds', type=int, default=5)
    parser.add_argument('--folds', type=int, default=5)
    parser.add_argument('--iterations', type=int, default=550)
    return parser.parse_args()


def main() -> None:
    warnings.filterwarnings('ignore', category=RuntimeWarning)
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected_seeds = RANDOM_SEEDS[: args.seeds]
    started = time.perf_counter()

    bundle = load_bundle(args.root)
    profile = dataset_profile(bundle)
    print(json.dumps(profile, ensure_ascii=False, indent=2), flush=True)

    feature_sets = prepare_train_feature_sets(bundle, selected_seeds)
    predictions, importance = run_grouped_benchmark(
        feature_sets,
        folds=args.folds,
        iterations=args.iterations,
    )
    seed_metrics = metric_table(predictions)

    ablation = run_ablation(
        feature_sets,
        seed=selected_seeds[0],
        folds=args.folds,
        iterations=args.iterations,
    )

    private_features = prepare_private_validation(bundle)
    private_predictions = fit_and_evaluate_private(
        feature_sets,
        private_features,
        args.iterations,
    )
    private_metrics = metric_table(private_predictions, group_column='regime')
    slices = slice_table(predictions, 'ensemble_clip')

    predictions.to_csv(args.output_dir / 'oof_predictions.csv', index=False, encoding='utf-8')
    seed_metrics.to_csv(args.output_dir / 'metrics_by_seed.csv', index=False, encoding='utf-8')
    private_metrics.to_csv(args.output_dir / 'private_validation.csv', index=False, encoding='utf-8')
    ablation.to_csv(args.output_dir / 'ablation_by_fold.csv', index=False, encoding='utf-8')
    slices.to_csv(args.output_dir / 'error_slices.csv', index=False, encoding='utf-8')
    importance.mean(axis=1).sort_values(ascending=False).rename('importance').to_csv(
        args.output_dir / 'feature_importance.csv',
        encoding='utf-8',
    )
    with (args.output_dir / 'dataset_profile.json').open('w', encoding='utf-8') as stream:
        json.dump(profile, stream, ensure_ascii=False, indent=2)
    write_report(
        args.output_dir,
        profile,
        seed_metrics,
        private_metrics,
        ablation,
        slices,
    )
    print(f'Готово за {time.perf_counter() - started:.1f} с', flush=True)


if __name__ == '__main__':
    main()
