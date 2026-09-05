from datetime import date
from types import SimpleNamespace

from app.risk import build_risk_profile


def observation(day: str, ndvi: float | None, *, valid: float = 92, cloud: float = 8) -> SimpleNamespace:
    return SimpleNamespace(
        date=date.fromisoformat(day),
        primary_ndvi=ndvi,
        primary_ndvi_pred=ndvi if ndvi is not None else 0.5,
        prediction_uncertainty=0.03,
        s2_ndvi=ndvi,
        landsat_ndvi=None,
        modis_ndvi=None,
        s2_evi=0.4 if ndvi is not None else None,
        landsat_evi=None,
        s2_ndwi=-0.15 if ndvi is not None else None,
        landsat_ndwi=None,
        era5_temp_c=24,
        era5_precip_mm=0,
        valid_pixels=valid,
        cloud_cover=cloud,
        is_imputed=ndvi is None,
    )


def test_risk_uses_robust_history_and_only_information_available_at_cutoff() -> None:
    rows = []
    for year, values in ((2022, (0.70, 0.68)), (2023, (0.72, 0.69)), (2024, (0.68, 0.67)), (2025, (0.71, 0.70))):
        rows.extend([observation(f"{year}-07-01", values[0]), observation(f"{year}-07-10", values[1])])
    rows.extend(
        [
            observation("2026-07-01", 0.67),
            observation("2026-07-08", 0.48),
            observation("2026-07-10", 0.39),
            observation("2026-07-20", 0.83),
        ]
    )

    profile = build_risk_profile(rows, 100, date(2026, 7, 10))

    assert profile["signal"]["risk_state"] == "confirmed_anomaly"
    assert profile["signal"]["reference_seasons"] == 4
    assert profile["signal"]["quality"]["causal"] is True
    assert profile["signal"]["as_of"] == "2026-07-10"
    assert all(point["date"] <= "2026-07-10" for point in profile["points"])


def test_risk_is_explicit_when_three_reference_seasons_are_not_available() -> None:
    rows = [observation("2025-06-10", 0.6), observation("2026-06-10", 0.3)]
    profile = build_risk_profile(rows, 20, date(2026, 6, 10))

    assert profile["signal"]["risk_state"] == "insufficient_data"
    assert profile["signal"]["confidence"] == 0
    assert profile["signal"]["robust_z"] is None
