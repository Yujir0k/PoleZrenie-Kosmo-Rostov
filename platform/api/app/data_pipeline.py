from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import numpy as np
import pandas as pd


MODEL_COLUMNS = [
    "anon_polygon_id",
    "date",
    "s2_ndvi",
    "s2_evi",
    "s2_ndwi",
    "landsat_ndvi",
    "landsat_evi",
    "landsat_ndwi",
    "modis_ndvi",
    "modis_evi",
    "era5_temp_c",
    "era5_precip_mm",
    "year",
    "primary_ndvi",
    "doy",
    "ndvi_climatology_mean",
    "ndvi_climatology_std",
    "ndvi_zscore",
    "n_reference_years",
    "status",
    "crop_type",
]


def _source_frame(records: Iterable[dict], prefix: str, value_columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    expected = ["date", *value_columns]
    if frame.empty:
        # Явные типы не дают pandas превратить пустой источник в object-колонки
        # и сохраняют стабильность каскада при частичной недоступности данных.
        return pd.DataFrame(
            {
                "date": pd.Series(dtype="datetime64[ns]"),
                **{column: pd.Series(dtype=float) for column in value_columns},
            }
        )
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    for column in value_columns:
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    # Один полигон может пересекать две спутниковые гранулы в один день.
    # Медиана не удваивает дату и устойчива к краевым пикселям гранулы.
    numeric = [column for column in expected if column != "date"]
    return frame[expected].groupby("date", as_index=False)[numeric].median(numeric_only=True)


def _season_grid(start_year: int, end_date: date) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for year in range(start_year, end_date.year + 1):
        start = pd.Timestamp(year=year, month=4, day=1)
        finish = min(pd.Timestamp(year=year, month=10, day=31), pd.Timestamp(end_date))
        if finish >= start:
            pieces.append(pd.DataFrame({"date": pd.date_range(start, finish, freq="D")}))
    if not pieces:
        raise ValueError("Выбранный период не пересекает сезон 1 апреля — 31 октября")
    return pd.concat(pieces, ignore_index=True)


def _climatology(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["year"] = result["date"].dt.year
    result["doy"] = result["date"].dt.dayofyear
    means = np.full(len(result), np.nan, dtype=float)
    scales = np.full(len(result), np.nan, dtype=float)
    counts = np.zeros(len(result), dtype=int)
    observed = result[result["primary_ndvi"].notna()][["year", "doy", "primary_ndvi"]]

    for year in result["year"].unique():
        positions = result.index[result["year"] == year]
        reference = observed[observed["year"] != year]
        for position in positions:
            doy = int(result.at[position, "doy"])
            window = reference[(reference["doy"] - doy).abs() <= 7]
            per_season = window.groupby("year")["primary_ndvi"].median().dropna()
            counts[position] = int(per_season.size)
            if per_season.size < 3:
                continue
            values = per_season.to_numpy(dtype=float)
            median = float(np.median(values))
            means[position] = median
            scales[position] = max(0.04, float(1.4826 * np.median(np.abs(values - median))))

    result["ndvi_climatology_mean"] = means
    result["ndvi_climatology_std"] = scales
    result["n_reference_years"] = counts
    usable_scale = result["ndvi_climatology_std"].where(result["ndvi_climatology_std"] >= 0.04)
    result["ndvi_zscore"] = (result["primary_ndvi"] - result["ndvi_climatology_mean"]) / usable_scale
    result["status"] = np.select(
        [result["ndvi_zscore"] < -2, result["ndvi_zscore"] < -1],
        ["critical", "warning"],
        default="normal",
    )
    return result


def build_model_dataset(
    *,
    polygon_id: str,
    crop_type: str,
    start_year: int,
    end_date: date,
    sentinel2: Iterable[dict],
    landsat: Iterable[dict],
    modis: Iterable[dict],
    era5: Iterable[dict],
) -> pd.DataFrame:
    """Приводит реальные агрегаты источников к контракту обеих моделей."""
    frame = _season_grid(start_year, end_date)
    sources = [
        _source_frame(
            sentinel2,
            "s2",
            ["s2_ndvi", "s2_evi", "s2_ndwi", "s2_valid_pixels", "s2_cloud_cover"],
        ),
        _source_frame(
            landsat,
            "landsat",
            [
                "landsat_ndvi",
                "landsat_evi",
                "landsat_ndwi",
                "landsat_valid_pixels",
                "landsat_cloud_cover",
            ],
        ),
        _source_frame(modis, "modis", ["modis_ndvi", "modis_evi", "modis_valid_pixels"]),
        _source_frame(era5, "era5", ["era5_temp_c", "era5_precip_mm"]),
    ]
    for source in sources:
        frame = frame.merge(source, on="date", how="left", validate="one_to_one")

    frame["anon_polygon_id"] = str(polygon_id)
    frame["crop_type"] = crop_type or "Культура не указана"
    # Каскад совпадает с правилом, использованным в конкурсном train.
    frame["primary_ndvi"] = (
        frame["s2_ndvi"].combine_first(frame["landsat_ndvi"]).combine_first(frame["modis_ndvi"])
    )
    frame = _climatology(frame)
    frame["is_synthetic_gap"] = False
    ordered = [*MODEL_COLUMNS, "is_synthetic_gap"]
    diagnostics = [column for column in frame.columns if column not in ordered]
    result = frame[ordered + diagnostics].sort_values("date").reset_index(drop=True)
    if result.duplicated(["anon_polygon_id", "date"]).any():
        raise ValueError("Сборщик сформировал повторяющиеся даты полигона")
    return result


def model_dataset_records(frame: pd.DataFrame) -> list[dict]:
    """JSON-safe сериализация без ложных нулей вместо отсутствующих измерений."""
    safe = frame.copy()
    safe["date"] = pd.to_datetime(safe["date"]).dt.strftime("%Y-%m-%d")
    safe = safe.replace({np.nan: None, np.inf: None, -np.inf: None})
    return safe.to_dict(orient="records")
