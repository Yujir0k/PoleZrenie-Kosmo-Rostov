import sys
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
from pathlib import Path

from app.analysis import PoleZrenieAnalysisAdapter, build_submission
from app.data_pipeline import MODEL_COLUMNS, build_model_dataset, model_dataset_records
from app.ml.anomaly_core import detect_anomalies, load_artifact
from app.providers.gee import EarthEngineProvider


def test_scene_asset_ids_open_the_exact_real_images() -> None:
    assert EarthEngineProvider._scene_asset_id("20221211T082341_20221211T082336_T37TFM", "sentinel2") == (
        "COPERNICUS/S2_SR_HARMONIZED/20221211T082341_20221211T082336_T37TFM"
    )
    assert EarthEngineProvider._scene_asset_id("LC08_L2SP_174027_20221220_20221227_02_T1", "landsat") == (
        "LANDSAT/LC08/C02/T1_L2/LC08_174027_20221220"
    )
    assert EarthEngineProvider._scene_asset_id("2022_12_19", "modis") == "MODIS/061/MOD13Q1/2022_12_19"


def test_multisource_dataset_matches_model_contract_and_cascade() -> None:
    frame = build_model_dataset(
        polygon_id="osm-real-field",
        crop_type="Озимая пшеница",
        start_year=2024,
        end_date=date(2024, 4, 3),
        sentinel2=[{"date": "2024-04-01", "s2_ndvi": 0.61, "s2_evi": 0.4, "s2_ndwi": -0.1}],
        landsat=[
            {"date": "2024-04-01", "landsat_ndvi": 0.42, "landsat_evi": 0.3, "landsat_ndwi": -0.2},
            {"date": "2024-04-02", "landsat_ndvi": 0.48, "landsat_evi": 0.32, "landsat_ndwi": -0.18},
        ],
        modis=[{"date": "2024-04-03", "modis_ndvi": 0.39, "modis_evi": 0.28}],
        era5=[
            {"date": "2024-04-01", "era5_temp_c": 13.2, "era5_precip_mm": 0.0},
            {"date": "2024-04-02", "era5_temp_c": 14.1, "era5_precip_mm": 1.4},
            {"date": "2024-04-03", "era5_temp_c": 15.0, "era5_precip_mm": 0.2},
        ],
    )

    assert frame.columns[: len(MODEL_COLUMNS)].tolist() == MODEL_COLUMNS
    assert frame["primary_ndvi"].tolist() == [0.61, 0.48, 0.39]
    assert not frame.duplicated(["anon_polygon_id", "date"]).any()
    assert model_dataset_records(frame)[0]["ndvi_climatology_mean"] is None


def test_confirmed_v8_submission_artifact_is_used_exactly() -> None:
    adapter = PoleZrenieAnalysisAdapter()
    confirmed = adapter._v8_predictions().iloc[0]
    frame = pd.DataFrame(
        {
            "anon_polygon_id": [confirmed["anon_polygon_id"]],
            "date": [confirmed["date"]],
            "primary_ndvi": [np.nan],
            "is_synthetic_gap": [True],
        }
    )

    result = build_submission(frame, adapter)
    assert result.iloc[0]["primary_ndvi_true"] == round(float(confirmed["primary_ndvi_pred"]), 10)


def test_anomaly_model_handles_an_unseen_field_from_input_history() -> None:
    rows = []
    for year in range(2021, 2026):
        for day in pd.date_range(f"{year}-04-01", f"{year}-10-31"):
            phase = np.sin((day.dayofyear - 91) / 212 * np.pi)
            ndvi, evi, ndwi = 0.25 + 0.5 * phase, 0.18 + 0.38 * phase, -0.2 + 0.18 * phase
            if year == 2025 and 180 <= day.dayofyear <= 197:
                ndvi, evi, ndwi = ndvi - 0.3, evi - 0.25, ndwi - 0.25
            rows.append(
                {
                    "anon_polygon_id": "unseen-real-field",
                    "date": day,
                    "primary_ndvi": ndvi,
                    "s2_evi": evi,
                    "s2_ndwi": ndwi,
                    "era5_temp_c": 20.0,
                    "era5_precip_mm": 1.0,
                    "crop_type": "Тестовая культура",
                }
            )
    artifact = Path(__file__).parents[1] / "app" / "ml" / "artifacts" / "anomaly_detector.joblib"
    events, _, skipped, quality = detect_anomalies(pd.DataFrame(rows), load_artifact(artifact))

    assert skipped.empty
    assert quality.empty
    assert len(events) == 1
    assert events.iloc[0]["normal_source"] == "input_history"
    assert "EVI" in events.iloc[0]["confirming_signals"]
    assert "NDWI" in events.iloc[0]["confirming_signals"]


def test_scene_catalog_keeps_winter_sources_and_date_specific_weather() -> None:
    catalog = EarthEngineProvider._scene_catalog(
        sentinel2=[
            {"date": "2022-01-10", "scene_id": "cloudy", "s2_ndvi": 0.1, "s2_evi": 0.08, "s2_ndwi": -0.2, "s2_cloud_cover": 70, "s2_valid_pixels": 20},
            {"date": "2022-01-10", "scene_id": "clear", "s2_ndvi": 0.2, "s2_evi": 0.15, "s2_ndwi": -0.1, "s2_cloud_cover": 15, "s2_valid_pixels": 90},
        ],
        landsat=[{"date": "2022-03-23", "scene_id": "l8", "landsat_ndvi": 0.3, "landsat_evi": 0.2, "landsat_ndwi": -0.05, "landsat_cloud_cover": 10, "landsat_valid_pixels": 95}],
        modis=[{"date": "2022-01-01", "scene_id": "m", "modis_ndvi": 0.35, "modis_evi": 0.22, "modis_valid_pixels": 100}],
        era5=[
            {"date": "2022-01-09", "era5_temp_c": -3.0, "era5_precip_mm": 1.0},
            {"date": "2022-01-10", "era5_temp_c": -1.5, "era5_precip_mm": 2.0},
        ],
    )

    assert len(catalog) == 3
    sentinel = next(scene for scene in catalog if scene["satellite"] == "Sentinel‑2")
    assert sentinel["scene_id"] == "clear"
    assert sentinel["temperature_c"] == -1.5
    assert sentinel["precipitation_7d_mm"] == 3.0


def test_collection_continues_when_some_sources_are_unavailable(monkeypatch) -> None:
    provider = EarthEngineProvider()
    monkeypatch.setattr(provider, "_initialize", lambda: None)
    monkeypatch.setitem(sys.modules, "ee", SimpleNamespace(Geometry=lambda geometry: geometry))

    def unavailable(*_args):
        raise ConnectionError("temporary provider failure")

    monkeypatch.setattr(provider, "_sentinel2_rows", unavailable)
    monkeypatch.setattr(
        provider,
        "_landsat_rows",
        lambda *_args: [
            {
                "date": "2024-04-01",
                "landsat_ndvi": 0.52,
                "landsat_evi": 0.31,
                "landsat_ndwi": -0.12,
                "scene_id": "real-landsat-scene",
                "satellite": "Landsat 8",
            }
        ],
    )
    monkeypatch.setattr(provider, "_modis_rows", lambda *_args: [])
    monkeypatch.setattr(provider, "_era5_rows", unavailable)
    monkeypatch.setattr(provider, "agricultural_profile", unavailable)

    dataset, profile = provider.collect_model_dataset(
        geometry={"type": "Polygon", "coordinates": []},
        polygon_id="partial-source-field",
        crop_type="Пшеница",
        start_year=2024,
        end_date=date(2024, 4, 3),
    )

    assert dataset["primary_ndvi"].notna().sum() == 1
    assert dataset.loc[0, "primary_ndvi"] == 0.52
    assert profile["degraded"] is True
    assert profile["available_sources"] == ["landsat"]
    assert set(profile["missing_sources"]) == {"sentinel2", "modis", "era5_land", "worldcover"}
    assert profile["source_status"]["sentinel2"]["status"] == "error"
    assert profile["source_status"]["modis"]["status"] == "no_data"
    assert profile["worldcover_cropland_percent"] is None


def test_collection_stops_only_when_all_vegetation_sources_are_unusable(monkeypatch) -> None:
    provider = EarthEngineProvider()
    monkeypatch.setattr(provider, "_initialize", lambda: None)
    monkeypatch.setitem(sys.modules, "ee", SimpleNamespace(Geometry=lambda geometry: geometry))
    monkeypatch.setattr(provider, "_sentinel2_rows", lambda *_args: [])
    monkeypatch.setattr(provider, "_landsat_rows", lambda *_args: [])
    monkeypatch.setattr(provider, "_modis_rows", lambda *_args: [])
    monkeypatch.setattr(
        provider,
        "_era5_rows",
        lambda *_args: [{"date": "2024-04-01", "era5_temp_c": 12.0, "era5_precip_mm": 1.0}],
    )
    monkeypatch.setattr(
        provider,
        "agricultural_profile",
        lambda *_args: {
            "worldcover_year": 2021,
            "worldcover_cropland_percent": 92.0,
            "is_verified_cropland": True,
        },
    )

    with np.testing.assert_raises_regex(RuntimeError, "ни один спутниковый источник"):
        provider.collect_model_dataset(
            geometry={"type": "Polygon", "coordinates": []},
            polygon_id="weather-only-field",
            crop_type="Пшеница",
            start_year=2024,
            end_date=date(2024, 4, 3),
        )
