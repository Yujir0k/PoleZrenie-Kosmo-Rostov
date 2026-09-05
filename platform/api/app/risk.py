from __future__ import annotations

from datetime import date, timedelta
from math import isfinite
from typing import Any, Iterable

import numpy as np
import pandas as pd


NORM_WINDOW_DAYS = 7
MIN_REFERENCE_SEASONS = 3


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _frame(rows: Iterable[Any]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for row in rows:
        records.append(
            {
                "date": pd.Timestamp(row.date),
                "observed": _number(row.primary_ndvi),
                "restored": _number(row.primary_ndvi_pred),
                "uncertainty": _number(row.prediction_uncertainty),
                "s2": _number(row.s2_ndvi),
                "landsat": _number(row.landsat_ndvi),
                "modis": _number(row.modis_ndvi),
                "evi": _number(row.s2_evi) if _number(row.s2_evi) is not None else _number(row.landsat_evi),
                "ndwi": _number(row.s2_ndwi) if _number(row.s2_ndwi) is not None else _number(row.landsat_ndwi),
                "temperature": _number(row.era5_temp_c),
                "precipitation": _number(row.era5_precip_mm),
                "valid_pixels": _number(row.valid_pixels),
                "cloud_cover": _number(row.cloud_cover),
                "is_imputed": bool(row.is_imputed),
            }
        )
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"]).astype("datetime64[ns]")
    frame["year"] = frame["date"].dt.year
    frame["doy"] = frame["date"].dt.dayofyear
    return frame.sort_values("date").reset_index(drop=True)


def _robust_reference(frame: pd.DataFrame, year: int, doy: int, value_column: str = "observed") -> dict[str, Any]:
    history = frame[(frame["year"] < year) & frame[value_column].notna()].copy()
    history = history[(history["doy"] - doy).abs() <= NORM_WINDOW_DAYS]
    if history.empty:
        return {"median": None, "q10": None, "q90": None, "scale": None, "seasons": 0}
    per_season = history.groupby("year")[value_column].median().dropna()
    seasons = int(per_season.size)
    if seasons < MIN_REFERENCE_SEASONS:
        return {"median": None, "q10": None, "q90": None, "scale": None, "seasons": seasons}
    values = per_season.to_numpy(dtype=float)
    median = float(np.median(values))
    mad = float(1.4826 * np.median(np.abs(values - median)))
    return {
        "median": median,
        "q10": float(np.quantile(values, 0.10)),
        "q90": float(np.quantile(values, 0.90)),
        "scale": max(0.04, mad),
        "seasons": seasons,
    }


def _source(row: pd.Series) -> str | None:
    sources = [name for name, column in (("Sentinel-2", "s2"), ("Landsat 8/9", "landsat"), ("MODIS", "modis")) if _number(row[column]) is not None]
    return " + ".join(sources) or None


def _slope(observed: pd.DataFrame, current_date: pd.Timestamp) -> float | None:
    current_date = pd.Timestamp(current_date)
    lower = current_date.date() - timedelta(days=21)
    recent = observed[observed["date"].dt.date.between(lower, current_date.date())].tail(5)
    if len(recent) < 2:
        return None
    elapsed = (recent["date"].iloc[-1] - recent["date"].iloc[0]).days
    if elapsed <= 0:
        return None
    return float((recent["observed"].iloc[-1] - recent["observed"].iloc[0]) / elapsed * 14)


def _state(zscore: float | None, projected_z_14d: float | None, slope_14d: float | None, persistent_low: int) -> tuple[str, int]:
    if zscore is None:
        return "insufficient_data", 0
    decline = min(20.0, max(0.0, -(slope_14d or 0.0) / 0.08 * 20.0))
    deviation = min(80.0, max(0.0, (-zscore - 0.35) / 2.4 * 80.0))
    score = int(round(min(100.0, deviation + decline)))
    if zscore <= -2.0 and persistent_low >= 2:
        return "confirmed_anomaly", max(score, 85)
    if zscore <= -1.2 or (projected_z_14d is not None and projected_z_14d <= -1.2) or (zscore <= -0.7 and (slope_14d or 0.0) <= -0.04):
        return "early_risk", max(score, 55)
    if zscore <= -0.5 or (slope_14d or 0.0) <= -0.03:
        return "watch", max(score, 25)
    return "normal", score


def _confidence(reference_seasons: int, valid_pixels: float | None, cloud_cover: float | None) -> tuple[int, str]:
    if reference_seasons < MIN_REFERENCE_SEASONS:
        return 0, "insufficient"
    score = min(70, 35 + reference_seasons * 7)
    if valid_pixels is not None and valid_pixels >= 25:
        score += 15
    if cloud_cover is not None:
        score += 10 if cloud_cover <= 25 else 4 if cloud_cover <= 60 else 0
    score = min(95, score)
    return score, "high" if score >= 80 else "medium" if score >= 60 else "low"


def build_risk_profile(rows: Iterable[Any], area_ha: float, as_of: date | None = None) -> dict[str, Any]:
    """Build an explainable, leakage-free current risk signal from real measurements."""
    frame = _frame(rows)
    if frame.empty:
        return {"state": "not_analyzed", "points": [], "signal": None}
    cutoff = pd.Timestamp(as_of or frame["date"].max().date())
    target_year = int(cutoff.year)
    current = frame[(frame["year"] == target_year) & (frame["date"] <= cutoff)].copy()
    observed = current[current["observed"].notna()].copy()
    points: list[dict[str, Any]] = []
    low_flags: list[bool] = []
    for _, row in current.iterrows():
        reference = _robust_reference(frame, target_year, int(row["doy"]))
        measured = _number(row["observed"])
        zscore = None
        if measured is not None and reference["median"] is not None:
            zscore = (measured - reference["median"]) / reference["scale"]
        low_flags.append(zscore is not None and zscore < -1.0)
        points.append(
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "robust_median": reference["median"],
                "robust_q10": reference["q10"],
                "robust_q90": reference["q90"],
                "robust_z": zscore,
                "norm_sample_count": reference["seasons"],
                "observation_source": _source(row),
                "cloud_cover": _number(row["cloud_cover"]),
            }
        )
    if observed.empty:
        return {"state": "insufficient_data", "points": points, "signal": None}

    latest_index = int(observed.index[-1])
    latest = frame.loc[latest_index]
    latest_date = pd.Timestamp(latest["date"])
    point_index = current.index.get_loc(latest_index)
    technical = points[point_index]
    zscore = _number(technical["robust_z"])
    slope_14d = _slope(observed, latest_date)
    recent_flags = [flag for flag, row_date in zip(low_flags, current["date"], strict=True) if pd.Timestamp(row_date).date() >= latest_date.date() - timedelta(days=21)]
    persistent_low = sum(recent_flags)
    projected_z_14d = None
    if zscore is not None and slope_14d is not None and technical["robust_median"] is not None:
        reference = _robust_reference(frame, target_year, int(latest["doy"]))
        if reference["scale"]:
            projected_z_14d = zscore + slope_14d / reference["scale"]
    state, risk_score = _state(zscore, projected_z_14d, slope_14d, persistent_low)
    confidence, confidence_level = _confidence(
        int(technical["norm_sample_count"]), _number(latest["valid_pixels"]), _number(latest["cloud_cover"])
    )

    context: list[str] = []
    hypothesis = "Причина не определяется без устойчивого отклонения и подтверждающих факторов"
    recommendation = "Продолжать наблюдение после следующей доступной спутниковой сцены"
    if zscore is not None:
        context.append(f"NDVI относительно медианы прошлых сезонов: z={zscore:.2f}")
    if slope_14d is not None:
        context.append(f"Изменение NDVI за сопоставимый 14-дневный темп: {slope_14d:+.3f}")
    if projected_z_14d is not None:
        context.append(f"Линейная проекция устойчивого z на 14 дней: {projected_z_14d:.2f} (не прогноз NDVI)")
    recent_weather = frame[frame["date"].dt.date.between(latest_date.date() - timedelta(days=13), latest_date.date())]
    precipitation_14d = _number(recent_weather["precipitation"].sum(min_count=1))
    temperature_7d = _number(recent_weather.tail(7)["temperature"].mean())
    ndwi = _number(latest["ndwi"])
    if precipitation_14d is not None:
        context.append(f"Осадки ERA5-Land за 14 дней: {precipitation_14d:.1f} мм")
    if temperature_7d is not None:
        context.append(f"Средняя температура ERA5-Land за 7 дней: {temperature_7d:.1f} °C")
    if ndwi is not None:
        context.append(f"NDWI на сцене: {ndwi:.2f}")
    if state in {"early_risk", "confirmed_anomaly"}:
        if ndwi is not None and ndwi < 0:
            hypothesis = "Возможен водный стресс: отрицательный NDWI подтверждает дефицит влаги в растительном покрове"
        elif precipitation_14d is not None and precipitation_14d < 5:
            hypothesis = "Возможен дефицит осадков; вывод требует проверки на поле"
        else:
            hypothesis = "Устойчивое снижение NDVI; однозначная причина по доступным данным не подтверждена"
        recommendation = "Проверить поле в указанных точках и зафиксировать результат осмотра"
    elif state == "watch":
        hypothesis = "Есть ранний слабый сигнал, но порог подтверждённой аномалии не достигнут"
        recommendation = "Дождаться следующей сцены или провести выборочный осмотр"

    latest_day = latest_date.strftime("%Y-%m-%d")
    return {
        "state": "ready",
        "points": points,
        "signal": {
            "id": f"{latest.get('field_id', '') or 'field'}-{target_year}-{latest_day}",
            "as_of": latest_day,
            "risk_state": state,
            "risk_score": risk_score,
            "confidence": confidence,
            "confidence_level": confidence_level,
            "robust_z": zscore,
            "slope_14d": slope_14d,
            "projected_robust_z_14d": projected_z_14d,
            "lead_window_days": 14,
            "projection_disclaimer": "Экстраполяция текущего темпа для раннего внимания; не прогноз будущего NDVI",
            "reference_seasons": int(technical["norm_sample_count"]),
            "observation_source": technical["observation_source"],
            "observation": (
                f"NDVI {float(latest['observed']):.2f} по фактической сцене {technical['observation_source']} от {latest_day}"
            ),
            "context": context,
            "hypothesis": hypothesis,
            "recommendation": recommendation,
            "affected_area_ha": None,
            "affected_area_percent": None,
            "area_ha": area_ha,
            "quality": {
                "valid_pixels": _number(latest["valid_pixels"]),
                "cloud_cover": _number(latest["cloud_cover"]),
                "norm_method": "median + q10/q90 + MAD, окно ±7 дней",
                "causal": True,
            },
        },
    }
