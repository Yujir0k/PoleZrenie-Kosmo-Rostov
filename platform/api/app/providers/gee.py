from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

import pandas as pd

from app.config import Settings, get_settings
from app.data_pipeline import build_model_dataset
from app.providers.base import DataProvider, ProviderHealth


logger = logging.getLogger(__name__)


class EarthEngineProvider(DataProvider):
    """Инициализирует Earth Engine на сервере, не раскрывая учётные данные клиенту."""

    datasets = ["COPERNICUS/S2_SR_HARMONIZED", "LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2", "MODIS/061/MOD13Q1", "ECMWF/ERA5_LAND/DAILY_AGGR"]
    _initialization_lock = Lock()
    _initialized_signature: tuple[str | None, str | None] | None = None
    _map_access_verified_at = 0.0

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def configured(self) -> bool:
        return bool(self.settings.gee_project)

    def _initialize(self) -> None:
        import ee

        key_path = str(Path(self.settings.gee_service_account_file).resolve()) if self.settings.gee_service_account_file else None
        signature = (self.settings.gee_project, key_path)
        if type(self)._initialized_signature == signature:
            return
        with type(self)._initialization_lock:
            if type(self)._initialized_signature == signature:
                return
            if key_path:
                key_file = Path(key_path)
                service_account = json.loads(key_file.read_text(encoding="utf-8"))["client_email"]
                credentials = ee.ServiceAccountCredentials(service_account, str(key_file))
                ee.Initialize(credentials, project=self.settings.gee_project)
            else:
                ee.Initialize(project=self.settings.gee_project)
            type(self)._initialized_signature = signature

    @staticmethod
    def _scene_asset_id(scene_id: str, satellite: str) -> str:
        """Converts a stored real scene identifier into its exact GEE asset ID."""
        if "/" in scene_id:
            return scene_id
        if satellite == "sentinel2":
            return f"COPERNICUS/S2_SR_HARMONIZED/{scene_id}"
        if satellite == "modis":
            return f"MODIS/061/MOD13Q1/{scene_id}"
        parts = scene_id.split("_")
        if len(parts) >= 4 and parts[0] in {"LC08", "LC09"} and parts[1].startswith("L2"):
            scene_id = f"{parts[0]}_{parts[2]}_{parts[3]}"
        collection = "LANDSAT/LC09/C02/T1_L2" if scene_id.startswith("LC09") else "LANDSAT/LC08/C02/T1_L2"
        return f"{collection}/{scene_id}"

    def _check_map_access(self) -> None:
        """Проверяет возможность создавать временные map ID, нужные MapLibre."""
        import ee

        if time.monotonic() - type(self)._map_access_verified_at < 300:
            return
        self._initialize()
        ee.Image.constant(0).visualize(min=0, max=1).getMapId()
        type(self)._map_access_verified_at = time.monotonic()

    async def health(self) -> ProviderHealth:
        if not self.configured:
            return ProviderHealth("gee", "Google Earth Engine", "unavailable", "GEE_PROJECT и сервисный аккаунт не настроены", self.datasets, "Основной")
        try:
            await asyncio.wait_for(asyncio.to_thread(self._check_map_access), timeout=15)
            return ProviderHealth("gee", "Google Earth Engine", "connected", "API и спутниковые тайлы доступны", self.datasets, "Основной")
        except Exception as error:  # Ответ SDK зависит от настроек проекта и прав.
            message = str(error)
            if "earthengine.maps.create" in message:
                detail = "Добавьте сервисному аккаунту роль Earth Engine Resource Writer"
            else:
                detail = f"Ошибка подключения: {type(error).__name__}"
            return ProviderHealth("gee", "Google Earth Engine", "unavailable", detail, self.datasets, "Основной")

    def preview_descriptor(
        self,
        geometry: dict,
        start: str,
        end: str,
        layer: str = "ndvi",
        requested_date: str | None = None,
        satellite: str = "sentinel2",
        scene_id: str | None = None,
        known_scene_date: str | None = None,
        known_cloud_cover: float | None = None,
    ) -> dict:
        """Возвращает временный GEE tile URL точной сцены выбранного спутника."""
        import ee

        self._initialize()
        polygon = ee.Geometry(geometry)

        def mask_sentinel_clouds(image):
            scl = image.select("SCL")
            clear = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
            if layer != "rgb":
                clear = clear.And(scl.neq(11))
            return image.updateMask(clear).multiply(0.0001)

        def mask_landsat_clouds(image):
            qa = image.select("QA_PIXEL")
            clear = (
                qa.bitwiseAnd(1 << 1).eq(0)
                .And(qa.bitwiseAnd(1 << 2).eq(0))
                .And(qa.bitwiseAnd(1 << 3).eq(0))
                .And(qa.bitwiseAnd(1 << 4).eq(0))
            )
            if layer != "rgb":
                clear = clear.And(qa.bitwiseAnd(1 << 5).eq(0))
            return (
                image.select(["SR_B2", "SR_B3", "SR_B4", "SR_B5"], ["blue", "green", "red", "nir"])
                .multiply(0.0000275)
                .add(-0.2)
                .updateMask(clear)
            )

        if requested_date and not scene_id:
            requested = date.fromisoformat(requested_date)
            start = requested.isoformat()
            end = (requested + timedelta(days=1)).isoformat()
        if satellite == "sentinel2":
            collection = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(polygon).filterDate(start, end)
            cloud_property = "CLOUDY_PIXEL_PERCENTAGE"
            source_image = ee.Image(self._scene_asset_id(scene_id, satellite)) if scene_id else ee.Image(collection.sort(cloud_property).first())
            image = mask_sentinel_clouds(source_image)
            bands = {"blue": "B2", "green": "B3", "red": "B4", "nir": "B8"}
            satellite_label = "Sentinel‑2"
            native_resolution = 10
        elif satellite == "landsat":
            collection = (
                ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
                .filterBounds(polygon)
                .filterDate(start, end)
            )
            cloud_property = "CLOUD_COVER"
            source_image = ee.Image(self._scene_asset_id(scene_id, satellite)) if scene_id else ee.Image(collection.sort(cloud_property).first())
            image = mask_landsat_clouds(source_image)
            bands = {"blue": "blue", "green": "green", "red": "red", "nir": "nir"}
            satellite_label = "Landsat 8/9"
            native_resolution = 30
        elif satellite == "modis":
            if layer not in {"ndvi", "evi"}:
                raise ValueError("MODIS MOD13Q1 поддерживает слои NDVI и EVI")
            collection = ee.ImageCollection("MODIS/061/MOD13Q1").filterBounds(polygon).filterDate(start, end)
            cloud_property = None
            source_image = ee.Image(self._scene_asset_id(scene_id, satellite)) if scene_id else ee.Image(collection.first())
            clear = source_image.select("SummaryQA").lte(1)
            image = source_image.updateMask(clear)
            bands = {}
            satellite_label = "MODIS"
            native_resolution = 250
        else:
            raise ValueError("Неизвестный спутниковый источник")
        if not scene_id and collection.size().getInfo() == 0:
            raise RuntimeError(f"На выбранную дату нет сцены {satellite_label}")
        if layer == "rgb":
            rendered = image.visualize(bands=[bands["red"], bands["green"], bands["blue"]], min=0.02, max=0.3, gamma=1.2)
        elif layer == "evi":
            index = image.select("EVI").multiply(0.0001) if satellite == "modis" else image.expression(
                "2.5*((n-r)/(n+6*r-7.5*b+1))",
                {"n": image.select(bands["nir"]), "r": image.select(bands["red"]), "b": image.select(bands["blue"])},
            )
            rendered = index.visualize(min=0, max=0.9, palette=["b86b3f", "ead86c", "6ea85c", "1f623e"])
        elif layer == "ndwi":
            rendered = image.normalizedDifference([bands["green"], bands["nir"]]).visualize(min=-0.5, max=0.5, palette=["b87942", "ede3a8", "6db3b4", "23638c"])
        else:
            index = image.select("NDVI").multiply(0.0001) if satellite == "modis" else image.normalizedDifference([bands["nir"], bands["red"]])
            rendered = index.visualize(min=0, max=0.9, palette=["b86b3f", "ead86c", "83bd58", "1f623e"])
        map_id = rendered.getMapId()
        type(self)._map_access_verified_at = time.monotonic()
        acquired_at = known_scene_date or datetime.fromtimestamp(source_image.get("system:time_start").getInfo() / 1000, timezone.utc).date().isoformat()
        cloud_cover = known_cloud_cover
        if cloud_cover is None and cloud_property:
            cloud_cover = source_image.get(cloud_property).getInfo()
        return {
            "provider": "gee",
            "satellite": satellite_label,
            "native_resolution_m": native_resolution,
            "url": map_id["tile_fetcher"].url_format,
            "expires_in": 10_800,
            "requested_date": requested_date,
            "scene_date": acquired_at,
            "cloud_cover": cloud_cover,
        }

    def sentinel_preview_descriptor(self, geometry: dict, start: str, end: str, layer: str = "ndvi", requested_date: str | None = None) -> dict:
        """Обратная совместимость для клиентов, которые явно запрашивают Sentinel‑2."""
        return self.preview_descriptor(geometry, start, end, layer, requested_date, "sentinel2")

    def spatial_risk_descriptor(self, geometry: dict, scene_id: str, scene_date: str, threshold: float) -> dict:
        """Measures and maps real Sentinel-2 pixels below a supplied robust seasonal threshold."""
        import ee

        self._initialize()
        polygon = ee.Geometry(geometry)
        source = ee.Image(self._scene_asset_id(scene_id, "sentinel2"))
        scl = source.select("SCL")
        clear = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
        optical = source.select(["B4", "B8"], ["red", "nir"]).multiply(0.0001).updateMask(clear)
        ndvi = optical.normalizedDifference(["nir", "red"]).rename("ndvi").clip(polygon)
        pixel_area = ee.Image.pixelArea()
        options = {"geometry": polygon, "scale": 10, "bestEffort": True, "maxPixels": 100_000_000, "tileScale": 2}
        # Исторический Q10 может окрасить почти всё убранное поле. Для рабочего обхода
        # локализуем приоритет внутри снимка: берём худший квартиль, но никогда не
        # поднимаем порог выше исторической нижней границы.
        scene_q25 = ndvi.reduceRegion(ee.Reducer.percentile([25]), **options).get("ndvi_p25")
        operational_threshold = ee.Number(threshold).min(ee.Number(scene_q25))
        risk = ndvi.lt(operational_threshold).selfMask().rename("risk")
        affected = pixel_area.updateMask(risk).reduceRegion(ee.Reducer.sum(), **options).get("area")
        valid = pixel_area.updateMask(ndvi.mask()).reduceRegion(ee.Reducer.sum(), **options).get("area")
        samples = risk.sample(region=polygon, scale=10, numPixels=3, seed=37, geometries=True).getInfo()
        points = []
        for index, item in enumerate(samples.get("features", []), start=1):
            coordinates = item.get("geometry", {}).get("coordinates")
            if coordinates and len(coordinates) == 2:
                points.append({"title": f"Зона осмотра {index}", "longitude": coordinates[0], "latitude": coordinates[1]})
        values = ee.Dictionary({"affected": affected, "valid": valid, "scene_q25": scene_q25, "operational_threshold": operational_threshold}).getInfo()
        affected_m2 = float(values.get("affected") or 0)
        valid_m2 = float(values.get("valid") or 0)
        rendered = risk.visualize(min=0, max=1, palette=["d65345"], opacity=0.72)
        map_id = rendered.getMapId()
        return {
            "provider": "gee",
            "satellite": "Sentinel‑2",
            "scene_date": scene_date,
            "threshold": round(float(values.get("operational_threshold") or threshold), 3),
            "seasonal_threshold": round(float(threshold), 3),
            "local_percentile": 25,
            "native_resolution_m": 10,
            "affected_area_ha": round(affected_m2 / 10_000, 2),
            "affected_area_percent": round(100 * affected_m2 / valid_m2, 1) if valid_m2 else None,
            "valid_area_ha": round(valid_m2 / 10_000, 2),
            "inspection_candidates": points,
            "url": map_id["tile_fetcher"].url_format,
            "expires_in": 10_800,
        }

    @staticmethod
    def _scene_catalog(sentinel2: list[dict], landsat: list[dict], modis: list[dict], era5: list[dict]) -> list[dict]:
        """Полный круглогодичный каталог фактических сцен, отдельный от сезонной сетки модели."""
        weather = {str(row.get("date")): row for row in era5 if row.get("date")}
        precipitation = {day: row.get("era5_precip_mm") for day, row in weather.items()}
        definitions = [
            (sentinel2, "Sentinel‑2", "s2_ndvi", "s2_evi", "s2_ndwi", "s2_cloud_cover", "s2_valid_pixels"),
            (landsat, "Landsat 8/9", "landsat_ndvi", "landsat_evi", "landsat_ndwi", "landsat_cloud_cover", "landsat_valid_pixels"),
            (modis, "MODIS", "modis_ndvi", "modis_evi", None, None, "modis_valid_pixels"),
        ]
        best: dict[tuple[str, str], dict] = {}
        for rows, satellite, ndvi_key, evi_key, ndwi_key, cloud_key, valid_key in definitions:
            for row in rows:
                day = str(row.get("date") or "")
                ndvi = row.get(ndvi_key)
                if not day or ndvi is None:
                    continue
                weather_row = weather.get(day, {})
                current_date = date.fromisoformat(day)
                precip_7d = sum(
                    float(precipitation.get((current_date - timedelta(days=offset)).isoformat()) or 0)
                    for offset in range(7)
                    if precipitation.get((current_date - timedelta(days=offset)).isoformat()) is not None
                )
                candidate = {
                    "date": day,
                    "satellite": satellite,
                    "scene_id": row.get("scene_id"),
                    "ndvi": float(ndvi),
                    "evi": float(row[evi_key]) if row.get(evi_key) is not None else None,
                    "ndwi": float(row[ndwi_key]) if ndwi_key and row.get(ndwi_key) is not None else None,
                    "cloud_cover": float(row[cloud_key]) if cloud_key and row.get(cloud_key) is not None else None,
                    "valid_pixels": float(row[valid_key]) if row.get(valid_key) is not None else None,
                    "temperature_c": float(weather_row["era5_temp_c"]) if weather_row.get("era5_temp_c") is not None else None,
                    "precipitation_7d_mm": round(precip_7d, 3) if any(
                        precipitation.get((current_date - timedelta(days=offset)).isoformat()) is not None for offset in range(7)
                    ) else None,
                    "provider": "GEE",
                }
                key = (satellite, day)
                previous = best.get(key)
                candidate_score = (candidate["valid_pixels"] or -1, -(candidate["cloud_cover"] or 0))
                previous_score = ((previous or {}).get("valid_pixels") or -1, -((previous or {}).get("cloud_cover") or 0))
                if previous is None or candidate_score > previous_score:
                    best[key] = candidate
        return sorted(best.values(), key=lambda item: (item["date"], item["satellite"]), reverse=True)

    def field_observation(self, geometry: dict, end_date: date | None = None) -> dict:
        """Считает свежие спутниковые и погодные показатели внутри контура поля."""
        import ee

        self._initialize()
        polygon = ee.Geometry(geometry)
        period_end = end_date or datetime.now(timezone.utc).date()
        exclusive_end = period_end + timedelta(days=1)
        period_start = period_end - timedelta(days=120)

        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(polygon)
            .filterDate(period_start.isoformat(), exclusive_end.isoformat())
            .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 65))
            .sort("system:time_start", False)
        )
        if collection.size().getInfo() == 0:
            raise RuntimeError("За последние 120 дней нет подходящих сцен Sentinel-2")

        source = ee.Image(collection.first())

        def mask_for_analysis(image):
            scl = image.select("SCL")
            clear = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
            return image.updateMask(clear).select(["B8", "B4"]).multiply(0.0001)

        # Медиана нескольких последних сцен не оставляет небольшое поле пустым,
        # если ровно на самой свежей сцене над ним оказалось облако.
        reflectance = collection.limit(6).map(mask_for_analysis).median()
        ndvi = reflectance.normalizedDifference(["B8", "B4"]).rename("ndvi")
        reduction_options = {"geometry": polygon, "scale": 20, "bestEffort": True, "maxPixels": 100_000_000}
        ndvi_mean = ndvi.reduceRegion(reducer=ee.Reducer.mean(), **reduction_options).get("ndvi")
        valid_fraction = (
            ndvi.mask().rename("valid")
            .unmask(0)
            .reduceRegion(reducer=ee.Reducer.mean(), **reduction_options)
            .get("valid")
        )

        scene_day = ee.Date(source.get("system:time_start"))
        weather_collection = ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR").sort("system:time_start", False)
        latest_weather_day = ee.Date(ee.Image(weather_collection.first()).get("system:time_start"))
        weather_start = latest_weather_day.advance(-6, "day")
        weather_end = latest_weather_day.advance(1, "day")
        weather = weather_collection.filterDate(weather_start, weather_end)
        temperature = weather.select("temperature_2m").mean().subtract(273.15).rename("temperature")
        precipitation = weather.select("total_precipitation_sum").sum().multiply(1000).rename("precipitation")
        # ERA5-Land имеет сетку около 11 км: для маленького поля берём ячейку,
        # содержащую центроид, иначе reduceRegion может не захватить центр пикселя.
        weather_options = {"geometry": polygon.centroid(1), "scale": 11_132, "bestEffort": True, "maxPixels": 10_000_000}
        temperature_mean = temperature.reduceRegion(reducer=ee.Reducer.mean(), **weather_options).get("temperature")
        precipitation_mean = precipitation.reduceRegion(reducer=ee.Reducer.mean(), **weather_options).get("precipitation")

        values = ee.Dictionary(
            {
                "ndvi": ndvi_mean,
                "valid_fraction": valid_fraction,
                "temperature_c": temperature_mean,
                "precipitation_7d_mm": precipitation_mean,
                "scene_date": scene_day.format("YYYY-MM-dd"),
                "weather_date": latest_weather_day.format("YYYY-MM-dd"),
                "cloud_cover": source.get("CLOUDY_PIXEL_PERCENTAGE"),
            }
        ).getInfo()
        if values.get("ndvi") is None:
            raise RuntimeError("В контуре нет валидных пикселей выбранной сцены Sentinel-2")

        return {
            "provider": "gee",
            "ndvi": round(float(values["ndvi"]), 3),
            "valid_pixels": round(float(values.get("valid_fraction") or 0) * 100),
            "temperature_c": round(float(values["temperature_c"]), 1) if values.get("temperature_c") is not None else None,
            "precipitation_7d_mm": round(float(values["precipitation_7d_mm"]), 1) if values.get("precipitation_7d_mm") is not None else None,
            "scene_date": values["scene_date"],
            "weather_date": values["weather_date"],
            "cloud_cover": round(float(values.get("cloud_cover") or 0), 1),
        }

    @staticmethod
    def _feature_rows(collection) -> list[dict]:
        payload = collection.getInfo()
        return [feature.get("properties", {}) for feature in payload.get("features", [])]

    def _sentinel2_rows(self, polygon, start: str, end: str) -> list[dict]:
        import ee

        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(polygon)
            .filterDate(start, end)
            .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 80))
        )

        def to_feature(image):
            scl = image.select("SCL")
            clear = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
            optical = image.select(["B2", "B3", "B4", "B8"]).multiply(0.0001).updateMask(clear)
            ndvi = optical.normalizedDifference(["B8", "B4"]).rename("s2_ndvi")
            evi = optical.expression(
                "2.5*((n-r)/(n+6*r-7.5*b+1))",
                {"n": optical.select("B8"), "r": optical.select("B4"), "b": optical.select("B2")},
            ).rename("s2_evi")
            ndwi = optical.normalizedDifference(["B3", "B8"]).rename("s2_ndwi")
            options = {
                "geometry": polygon,
                "scale": 10,
                "bestEffort": True,
                "maxPixels": 100_000_000,
                "tileScale": 2,
            }
            values = ee.Image.cat([ndvi, evi, ndwi]).reduceRegion(ee.Reducer.mean(), **options)
            valid = ndvi.mask().unmask(0).reduceRegion(ee.Reducer.mean(), **options).values().get(0)
            return ee.Feature(None, values).set(
                {
                    "date": image.date().format("YYYY-MM-dd"),
                    "s2_valid_pixels": ee.Number(valid).multiply(100),
                    "s2_cloud_cover": image.get("CLOUDY_PIXEL_PERCENTAGE"),
                    "scene_id": image.get("system:index"),
                    "satellite": "Sentinel-2",
                }
            )

        return self._feature_rows(ee.FeatureCollection(collection.map(to_feature)))

    def _landsat_rows(self, polygon, start: str, end: str) -> list[dict]:
        import ee

        collection = (
            ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
            .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
            .filterBounds(polygon)
            .filterDate(start, end)
            .filter(ee.Filter.lte("CLOUD_COVER", 85))
        )

        def to_feature(image):
            qa = image.select("QA_PIXEL")
            clear = (
                qa.bitwiseAnd(1 << 1)
                .eq(0)
                .And(qa.bitwiseAnd(1 << 2).eq(0))
                .And(qa.bitwiseAnd(1 << 3).eq(0))
                .And(qa.bitwiseAnd(1 << 4).eq(0))
                .And(qa.bitwiseAnd(1 << 5).eq(0))
            )
            optical = (
                image.select(["SR_B2", "SR_B3", "SR_B4", "SR_B5"], ["blue", "green", "red", "nir"])
                .multiply(0.0000275)
                .add(-0.2)
                .updateMask(clear)
            )
            ndvi = optical.normalizedDifference(["nir", "red"]).rename("landsat_ndvi")
            evi = optical.expression(
                "2.5*((n-r)/(n+6*r-7.5*b+1))",
                {"n": optical.select("nir"), "r": optical.select("red"), "b": optical.select("blue")},
            ).rename("landsat_evi")
            ndwi = optical.normalizedDifference(["green", "nir"]).rename("landsat_ndwi")
            options = {
                "geometry": polygon,
                "scale": 30,
                "bestEffort": True,
                "maxPixels": 100_000_000,
                "tileScale": 2,
            }
            values = ee.Image.cat([ndvi, evi, ndwi]).reduceRegion(ee.Reducer.mean(), **options)
            valid = ndvi.mask().unmask(0).reduceRegion(ee.Reducer.mean(), **options).values().get(0)
            return ee.Feature(None, values).set(
                {
                    "date": image.date().format("YYYY-MM-dd"),
                    "landsat_valid_pixels": ee.Number(valid).multiply(100),
                    "landsat_cloud_cover": image.get("CLOUD_COVER"),
                    "scene_id": image.get("LANDSAT_PRODUCT_ID"),
                    "satellite": image.get("SPACECRAFT_ID"),
                }
            )

        return self._feature_rows(ee.FeatureCollection(collection.map(to_feature)))

    def _modis_rows(self, polygon, start: str, end: str) -> list[dict]:
        import ee

        collection = ee.ImageCollection("MODIS/061/MOD13Q1").filterBounds(polygon).filterDate(start, end)

        def to_feature(image):
            clear = image.select("SummaryQA").lte(1)
            ndvi = image.select("NDVI").multiply(0.0001).updateMask(clear).rename("modis_ndvi")
            evi = image.select("EVI").multiply(0.0001).updateMask(clear).rename("modis_evi")
            options = {
                "geometry": polygon,
                "scale": 250,
                "bestEffort": True,
                "maxPixels": 10_000_000,
                "tileScale": 2,
            }
            values = ee.Image.cat([ndvi, evi]).reduceRegion(ee.Reducer.mean(), **options)
            valid = ndvi.mask().unmask(0).reduceRegion(ee.Reducer.mean(), **options).values().get(0)
            return ee.Feature(None, values).set(
                {
                    "date": image.date().format("YYYY-MM-dd"),
                    "modis_valid_pixels": ee.Number(valid).multiply(100),
                    "scene_id": image.get("system:index"),
                    "satellite": "MODIS Terra",
                }
            )

        return self._feature_rows(ee.FeatureCollection(collection.map(to_feature)))

    def _era5_rows(self, polygon, start: str, end: str) -> list[dict]:
        import ee

        # Сохраняем погоду за весь календарный год для карточки любой сцены.
        # Сезонную сетку апрель–октябрь по-прежнему формирует build_model_dataset.
        collection = ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR").filterDate(start, end)
        centroid = polygon.centroid(1)

        def to_feature(image):
            weather = ee.Image.cat(
                [
                    image.select("temperature_2m").subtract(273.15).rename("era5_temp_c"),
                    image.select("total_precipitation_sum").multiply(1000).rename("era5_precip_mm"),
                ]
            )
            values = weather.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=centroid,
                scale=11_132,
                bestEffort=True,
                maxPixels=1_000_000,
            )
            return ee.Feature(None, values).set("date", image.date().format("YYYY-MM-dd"))

        return self._feature_rows(ee.FeatureCollection(collection.map(to_feature)))

    def agricultural_profile(self, geometry: dict) -> dict:
        """Проверяет, какую долю контура WorldCover 2021 относит к пашне."""
        import ee

        self._initialize()
        polygon = ee.Geometry(geometry)
        landcover = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map")
        cropland_fraction = (
            landcover.eq(40)
            .rename("cropland")
            .reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=polygon,
                scale=10,
                bestEffort=True,
                maxPixels=100_000_000,
                tileScale=2,
            )
            .get("cropland")
            .getInfo()
        )
        if cropland_fraction is None:
            raise RuntimeError("WorldCover не вернул классификацию внутри контура")
        fraction = float(cropland_fraction)
        return {
            "worldcover_year": 2021,
            "worldcover_cropland_percent": round(fraction * 100, 1),
            "is_verified_cropland": fraction >= 0.50,
        }

    def collect_model_dataset(
        self,
        geometry: dict,
        polygon_id: str,
        crop_type: str,
        *,
        start_year: int | None = None,
        end_date: date | None = None,
    ) -> tuple[pd.DataFrame, dict]:
        """Собирает реальные источники, сохраняя анализ при частичной недоступности.

        Спутниковые продукты образуют каскад Sentinel-2 -> Landsat -> MODIS, поэтому
        отказ одного продукта не должен останавливать расчёт. ERA5-Land и
        WorldCover дополняют анализ, но не являются обязательными для
        восстановления NDVI. Ошибка допустима только тогда, когда ни один
        спутниковый источник не дал пригодных наблюдений растительности.
        """
        self._initialize()
        period_end = end_date or datetime.now(timezone.utc).date()
        first_year = start_year or period_end.year - 5
        if first_year > period_end.year:
            raise ValueError("Начальный год не может быть позже конечной даты")
        start = date(first_year, 4, 1).isoformat()
        end = (period_end + timedelta(days=1)).isoformat()
        import ee

        polygon = ee.Geometry(geometry)
        source_status: dict[str, dict[str, object]] = {}

        def collect_source(name: str, loader: Callable[[], list[dict]]) -> list[dict]:
            try:
                rows = list(loader() or [])
            except Exception as error:  # Один недоступный продукт не должен обрывать весь пайплайн.
                logger.exception("Источник %s недоступен при сборе данных поля", name)
                source_status[name] = {
                    "status": "error",
                    "rows": 0,
                    "detail": f"Ошибка источника: {type(error).__name__}",
                }
                return []
            source_status[name] = {
                "status": "available" if rows else "no_data",
                "rows": len(rows),
                "detail": None if rows else "Источник не вернул данных за выбранный период",
            }
            return rows

        sentinel2 = collect_source("sentinel2", lambda: self._sentinel2_rows(polygon, start, end))
        landsat = collect_source("landsat", lambda: self._landsat_rows(polygon, start, end))
        modis = collect_source("modis", lambda: self._modis_rows(polygon, start, end))
        era5 = collect_source("era5_land", lambda: self._era5_rows(polygon, start, end))
        dataset = build_model_dataset(
            polygon_id=polygon_id,
            crop_type=crop_type,
            start_year=first_year,
            end_date=period_end,
            sentinel2=sentinel2,
            landsat=landsat,
            modis=modis,
            era5=era5,
        )
        try:
            agricultural_profile = self.agricultural_profile(geometry)
            source_status["worldcover"] = {
                "status": "available",
                "rows": 1,
                "detail": None,
            }
        except Exception as error:  # Классификация земли полезна, но не нужна для расчёта NDVI.
            logger.exception("WorldCover недоступен при проверке контура")
            agricultural_profile = {
                "worldcover_year": 2021,
                "worldcover_cropland_percent": None,
                "is_verified_cropland": None,
            }
            source_status["worldcover"] = {
                "status": "error",
                "rows": 0,
                "detail": f"Ошибка источника: {type(error).__name__}",
            }

        missing = [
            name
            for name in ("sentinel2", "landsat", "modis", "era5_land", "worldcover")
            if source_status[name]["status"] != "available"
        ]
        available = [name for name in source_status if name not in missing]
        profile = {
            **agricultural_profile,
            "period_start": start,
            "period_end": period_end.isoformat(),
            "source_rows": {
                "sentinel2": len(sentinel2),
                "landsat": len(landsat),
                "modis": len(modis),
                "era5_land": len(era5),
            },
            "native_resolution_m": {
                "sentinel2": 10,
                "landsat": 30,
                "modis": 250,
                "era5_land": 11_132,
                "worldcover": 10,
            },
            "scene_catalog": self._scene_catalog(sentinel2, landsat, modis, era5),
            "source_status": source_status,
            "available_sources": available,
            "missing_sources": missing,
            "degraded": bool(missing),
        }
        if not dataset["primary_ndvi"].notna().any():
            unavailable_vegetation = [
                name for name in ("sentinel2", "landsat", "modis") if name in missing
            ]
            detail = ", ".join(unavailable_vegetation) or "валидные значения NDVI"
            raise RuntimeError(
                "Невозможно продолжить анализ: ни один спутниковый источник "
                f"не вернул пригодный NDVI ({detail})"
            )
        return dataset, profile
