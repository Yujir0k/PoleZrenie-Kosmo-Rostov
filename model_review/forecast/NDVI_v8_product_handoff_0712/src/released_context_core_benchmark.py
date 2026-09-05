"""Evaluate v7 core with released old-test targets used as context donors."""

from __future__ import annotations

import argparse
import json
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from benchmark import (
    DatasetBundle,
    build_peer_map,
    build_weather_clusters,
    source_labels,
)
from new_test_v7_clean_submission import (
    build_feature_sets,
    first_key_occurrence,
    prior_prediction,
    source_branch,
)


TRAIN_ZIP = Path(r'A:\Downloads\doc-1788536686.zip')
OLD_TEST = Path(r'A:\Downloads\doc-1788536731.csv')
GROUND_TRUTH = Path(r'A:\Downloads\doc-1788600416 (2).zip')
NEW_TEST = Path(r'A:\Downloads\New_test.csv')
ROOT = Path(r'A:\cosmo_autogluon')
COMMON_COLUMNS = [
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('--private', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--supplementary-context', type=Path, action='append', default=[])
    parser.add_argument('--rebuild-features', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--fixed-gated-weight', type=float, default=0.80)
    return parser.parse_args()


def released_old_frame() -> pd.DataFrame:
    old = pd.read_csv(OLD_TEST, parse_dates=['date'])
    with zipfile.ZipFile(GROUND_TRUTH) as archive:
        truth = pd.read_csv(
            archive.open('private_test_ground_truth.csv'), parse_dates=['date']
        )
    mapping = truth.set_index(['anon_polygon_id', 'date'])['primary_ndvi_true']
    old_index = pd.MultiIndex.from_frame(old[['anon_polygon_id', 'date']])
    values = mapping.reindex(old_index).to_numpy(float)
    selected = old['is_synthetic_gap'].to_numpy(bool)
    if np.isnan(values[selected]).any():
        raise ValueError('Released truth does not cover all old synthetic gaps')
    old.loc[selected, 'primary_ndvi'] = values[selected]
    old['source'] = source_labels(old)
    # Revealed targets add labels, but the target source remains the organizer
    # cascade inferred from available sensor measurements.
    old.loc[selected, 'source'] = source_labels(old.loc[selected])
    return old


def normalize_context(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output['date'] = pd.to_datetime(output['date'])
    for column in ('ndvi_climatology_mean', 'ndvi_climatology_std'):
        output[column] = np.nan
    output['source'] = source_labels(output)
    if 'is_synthetic_gap' in output:
        output.loc[output['is_synthetic_gap'], 'source'] = 'hidden'
    return output


def load_bundle(private_path: Path, supplementary: list[Path]) -> DatasetBundle:
    with zipfile.ZipFile(TRAIN_ZIP) as archive:
        train = pd.read_csv(archive.open('train_dataset.csv'), parse_dates=['date'])
    private = pd.read_csv(private_path, parse_dates=['date'])
    train = normalize_context(train)
    private = normalize_context(private)
    train['target_source'] = train['source']
    private['target_source'] = private['source']

    extras = [released_old_frame()]
    extras.extend(normalize_context(pd.read_csv(path)) for path in supplementary)
    private_keys = pd.MultiIndex.from_frame(private[['anon_polygon_id', 'date']])
    clean_extras: list[pd.DataFrame] = []
    for extra in extras:
        extra = normalize_context(extra)
        extra_keys = pd.MultiIndex.from_frame(extra[['anon_polygon_id', 'date']])
        clean_extras.append(extra.loc[~extra_keys.isin(private_keys), COMMON_COLUMNS])
    combined = (
        pd.concat(
            [train[COMMON_COLUMNS], *clean_extras, private[COMMON_COLUMNS]],
            ignore_index=True,
        )
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
    return DatasetBundle(
        train=train,
        private=private,
        combined=combined,
        key_to_index=key_to_index,
        peer_map=build_peer_map(combined),
        weather_cluster=build_weather_clusters(combined),
    )


def rmse(target: np.ndarray, prediction: np.ndarray) -> float:
    return float(np.sqrt(np.mean((target - prediction) ** 2)))


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    bundle = load_bundle(args.private, args.supplementary_context)
    train_parts, adaptation_parts, hidden = build_feature_sets(
        bundle, args.work_dir, args.rebuild_features
    )
    base = first_key_occurrence(train_parts)
    adaptation = first_key_occurrence(adaptation_parts)
    prior = prior_prediction(base, adaptation, hidden)
    gated, probabilities, classes = source_branch(base, adaptation, hidden)
    v4 = np.clip(0.53 * prior + 0.47 * gated, -0.10, 0.95)
    fixed_prediction = np.clip(
        (1.0 - args.fixed_gated_weight) * prior
        + args.fixed_gated_weight * gated,
        -0.10,
        0.95,
    )

    with zipfile.ZipFile(GROUND_TRUTH) as archive:
        truth = pd.read_csv(
            archive.open('private_test_ground_truth.csv'), parse_dates=['date']
        )
    evaluation = hidden[['anon_polygon_id', 'date']].merge(
        truth,
        on=['anon_polygon_id', 'date'],
        how='left',
        validate='one_to_one',
    )
    if evaluation['primary_ndvi_true'].isna().any():
        metrics = {'evaluation_available': False}
    else:
        target = evaluation['primary_ndvi_true'].to_numpy(float)
        blend_scores = {
            f'{weight:.2f}': rmse(target, weight * gated + (1.0 - weight) * prior)
            for weight in np.linspace(0.0, 1.0, 21)
        }
        metrics = {
            'evaluation_available': True,
            'rows': len(target),
            'prior_rmse': rmse(target, prior),
            'gated_rmse': rmse(target, gated),
            'v4_rmse': rmse(target, v4),
            'fixed_gated_weight': args.fixed_gated_weight,
            'fixed_prediction_rmse': rmse(target, fixed_prediction),
            'best_gated_weight': float(min(blend_scores, key=blend_scores.get)),
            'best_blend_rmse': min(blend_scores.values()),
            'blend_scores': blend_scores,
        }
    args.work_dir.mkdir(parents=True, exist_ok=True)
    diagnostics = hidden[['anon_polygon_id', 'date']].copy()
    diagnostics['prior'] = prior
    diagnostics['gated'] = gated
    diagnostics['v4'] = v4
    diagnostics['fixed_prediction'] = fixed_prediction
    for index, source in enumerate(classes):
        diagnostics[f'prob_{source}'] = probabilities[:, index]
    diagnostics.to_parquet(args.work_dir / 'core_predictions.parquet', index=False)
    if args.output is not None:
        submission = hidden[['anon_polygon_id', 'date']].copy()
        submission['date'] = submission['date'].dt.strftime('%Y-%m-%d')
        submission['primary_ndvi_true'] = fixed_prediction
        if submission.duplicated(['anon_polygon_id', 'date']).any():
            raise ValueError('Duplicate submission keys')
        if not np.isfinite(fixed_prediction).all():
            raise ValueError('Non-finite submission values')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        submission.to_csv(
            args.output, index=False, encoding='utf-8', float_format='%.10f'
        )
        metrics['output'] = str(args.output)
    metrics.update(
        {
            'combined_rows': len(bundle.combined),
            'combined_polygons': int(bundle.combined['anon_polygon_id'].nunique()),
            'base_rows': len(base),
            'adaptation_rows': len(adaptation),
            'fixed_gated_weight': args.fixed_gated_weight,
            'seconds': float(time.perf_counter() - started),
        }
    )
    (args.work_dir / 'core_metrics.json').write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
