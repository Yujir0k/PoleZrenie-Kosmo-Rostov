from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pandas as pd
from geoalchemy2.shape import from_shape
from pyproj import Geod
from shapely.geometry import MultiPolygon, mapping, shape
from sqlalchemy import delete, select

from app.analysis import load_analysis_adapter
from app.config import get_settings
from app.database import SessionLocal
from app.models import AnalysisJobModel, FieldModel, FieldObservationModel
from app.providers import EarthEngineProvider


GEOD = Geod(ellps="WGS84")
settings = get_settings()


VERIFIED_FIELD = {
    "id": "rostov-zernograd-osm-343247956",
    "name": "Тестовое поле Зерноград",
    "crop": "Культура не указана",
    "region": "Ростовская область",
    "area_ha": 104.23,
    "ndvi": 0.0,
    "delta": 0.0,
    "status": "normal",
    "source": "osm",
    "valid_pixels": 0,
    # Реальный объект OSM way/343247956, landuse=farmland, район Зернограда.
    "geometry": {
        "type": "Polygon",
        "coordinates": [[
            [40.4086589,46.7856921],[40.4084228,46.7858565],[40.4081808,46.7851579],
            [40.4078604,46.784166],[40.4077492,46.7839645],[40.4075432,46.7838122],
            [40.4071181,46.7836577],[40.4066341,46.7835323],[40.4063725,46.7833756],
            [40.4061436,46.7831718],[40.4059147,46.7830576],[40.4055975,46.7829412],
            [40.405385,46.7828449],[40.4050155,46.7825628],[40.4047768,46.7822717],
            [40.4045315,46.7820769],[40.4043975,46.7820567],[40.4042372,46.7821015],
            [40.4041751,46.7822426],[40.4041751,46.7831673],[40.4041281,46.7839277],
            [40.4041605,46.7862954],[40.4041903,46.7882979],[40.4054571,46.7877691],
            [40.4065971,46.7872182],[40.4077828,46.7865403],[40.4088146,46.7858197],
            [40.4095208,46.7852693],[40.4107439,46.7841604],[40.4115571,46.7833092],
            [40.4136278,46.7809443],[40.413506,46.7808998],[40.4155862,46.7784995],
            [40.4157648,46.7785495],[40.4170718,46.7770072],[40.4205367,46.7731631],
            [40.4205327,46.7730287],[40.4203662,46.7729824],[40.4202106,46.7729008],
            [40.4200076,46.7728647],[40.4197512,46.7728405],[40.4193933,46.7728588],
            [40.4186315,46.7730279],[40.4180383,46.7731538],[40.4174502,46.7731862],
            [40.4173068,46.7731621],[40.4172635,46.7730657],[40.4171294,46.7730083],
            [40.4156708,46.7730712],[40.4137415,46.7732225],[40.4098663,46.7735354],
            [40.4100573,46.7751513],[40.4101365,46.7752952],[40.4103317,46.7753371],
            [40.4105652,46.7752991],[40.4108006,46.7752611],[40.4111298,46.7752939],
            [40.4113805,46.7753463],[40.4116197,46.775463],[40.4117958,46.775501],
            [40.4119968,46.7754826],[40.412125,46.775362],[40.4121977,46.7752493],
            [40.4122934,46.7751392],[40.4123738,46.7750973],[40.4125058,46.7751458],
            [40.4127451,46.7754551],[40.4128924,46.7755665],[40.4131585,46.7756098],
            [40.413392,46.7756465],[40.413547,46.775712],[40.4136121,46.7758624],
            [40.4136886,46.7761599],[40.4138532,46.7764352],[40.4139336,46.7765898],
            [40.4138551,46.7767825],[40.4137594,46.7768428],[40.4135757,46.7768507],
            [40.4133786,46.7767982],[40.4132082,46.7767655],[40.4129097,46.7767379],
            [40.4126896,46.7767104],[40.4125709,46.7766593],[40.4124752,46.776578],
            [40.4122398,46.7765073],[40.4119661,46.7764496],[40.4117212,46.7764719],
            [40.4114838,46.7765558],[40.4113097,46.7765964],[40.4111776,46.7765898],
            [40.4109709,46.7765295],[40.4108312,46.7764745],[40.4106666,46.7764286],
            [40.4104121,46.776447],[40.4102456,46.7764824],[40.4098877,46.7765138],
            [40.409503,46.7766134],[40.4093441,46.7766868],[40.4092676,46.7767602],
            [40.4092772,46.7770682],[40.4093559,46.7778925],[40.4093884,46.7783689],
            [40.4094209,46.7788545],[40.4093949,46.7788822],[40.409326,46.7788835],
            [40.4092437,46.7788278],[40.4089868,46.7786302],[40.4087112,46.7782278],
            [40.4085619,46.7779762],[40.4084509,46.7777455],[40.4084107,46.77733],
            [40.4083782,46.7768687],[40.4083284,46.7765528],[40.4083093,46.7762775],
            [40.4082614,46.776098],[40.4081561,46.7758961],[40.4079801,46.7756458],
            [40.4076413,46.7753705],[40.4074691,46.7753037],[40.407205,46.7752054],
            [40.4070691,46.775035],[40.4069045,46.7746457],[40.4068069,46.7744124],
            [40.4067341,46.7740336],[40.4066829,46.7737786],[40.4038691,46.7739662],
            [40.4037803,46.774558],[40.4039575,46.7766905],[40.4041843,46.7810805],
            [40.404192,46.7812744],[40.4044446,46.7815182],[40.4062308,46.7827686],
            [40.40681,46.7831244],[40.4080604,46.7835766],[40.4086018,46.7837366],
            [40.4086624,46.7838193],[40.4085866,46.7839953],[40.4084369,46.7841693],
            [40.4083661,46.784358],[40.4084656,46.7848874],[40.4085479,46.7852937],
            [40.4085804,46.785447],[40.4086589,46.7856921]
        ]],
    },
}


def spatial_geometry(geometry: dict) -> object:
    polygon = shape(geometry)
    multipolygon = polygon if polygon.geom_type == "MultiPolygon" else MultiPolygon([polygon])
    if settings.database_url.startswith("sqlite"):
        return mapping(multipolygon)
    return from_shape(multipolygon, srid=4326)


def validate_geometry(geometry: dict) -> float:
    polygon = shape(geometry)
    if polygon.geom_type != "Polygon":
        raise ValueError("Поддерживается GeoJSON Polygon")
    if not polygon.is_valid:
        raise ValueError("Контур имеет самопересечения или другую ошибку геометрии")
    area_m2, _ = GEOD.geometry_area_perimeter(polygon)
    area_ha = abs(area_m2) / 10_000
    if area_ha <= 0.01:
        raise ValueError("Площадь контура слишком мала")
    if area_ha > 5_000:
        raise ValueError("Площадь ограничена 5 000 га")
    return round(area_ha, 2)


def _number(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _first_number(row, names: tuple[str, ...]) -> float | None:
    for name in names:
        value = _number(getattr(row, name, None))
        if value is not None:
            return value
    return None


def _timeseries_points(restored: pd.DataFrame, year: int) -> list[dict]:
    current = restored[restored["date"].dt.year == year].copy()
    points: list[dict] = []
    for row in current.itertuples(index=False):
        spread = _number(getattr(row, "prediction_uncertainty", None)) or 0.05
        climate = _number(row.ndvi_climatology_mean)
        climate_std = _number(row.ndvi_climatology_std)
        observed = _number(row.primary_ndvi)
        prediction = float(row.primary_ndvi_pred)
        valid = _first_number(row, ("s2_valid_pixels", "landsat_valid_pixels", "modis_valid_pixels"))
        points.append({
            "date": pd.Timestamp(row.date).strftime("%Y-%m-%d"),
            "observed": observed,
            "restored": prediction,
            "climate_mean": climate,
            "climate_low": climate - climate_std if climate is not None and climate_std is not None else None,
            "climate_high": climate + climate_std if climate is not None and climate_std is not None else None,
            "confidence_low": max(-0.1, prediction - spread),
            "confidence_high": min(0.95, prediction + spread),
            "s2": _number(row.s2_ndvi),
            "landsat": _number(row.landsat_ndvi),
            "modis": _number(row.modis_ndvi),
            "temperature": _number(row.era5_temp_c),
            "precipitation": _number(row.era5_precip_mm),
            "is_imputed": observed is None,
            "valid_pixels": valid,
            "provider": "gee",
        })
    return points


def _scene_records(frame: pd.DataFrame, field_id: str) -> list[dict]:
    scenes: list[dict] = []
    definitions = [
        ("s2_ndvi", "Sentinel‑2", "s2_cloud_cover", "s2_valid_pixels"),
        ("landsat_ndvi", "Landsat 8/9", "landsat_cloud_cover", "landsat_valid_pixels"),
        ("modis_ndvi", "MODIS", None, "modis_valid_pixels"),
    ]
    for value_column, satellite, cloud_column, valid_column in definitions:
        for row in frame[frame[value_column].notna()].itertuples(index=False):
            day = pd.Timestamp(row.date).strftime("%Y-%m-%d")
            scenes.append({
                "id": f"{field_id}-{satellite}-{day}",
                "date": day,
                "satellite": satellite,
                "cloud_cover": _number(getattr(row, cloud_column, None)) if cloud_column else None,
                "valid_pixels": _number(getattr(row, valid_column, None)),
                "provider": "GEE",
            })
    return sorted(scenes, key=lambda item: item["date"], reverse=True)


async def _update_job(job_id: str, progress: int, stage: str) -> None:
    async with SessionLocal() as session:
        job = await session.get(AnalysisJobModel, job_id)
        if not job:
            return
        job.status = "running"
        job.progress = progress
        job.stage = stage
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def run_analysis(job_id: str) -> None:
    """Сбор реальных данных → восстановление → объяснимые аномалии → БД."""
    try:
        await _update_job(job_id, 3, "Проверяем геометрию и источники")
        async with SessionLocal() as session:
            job = await session.get(AnalysisJobModel, job_id)
            field = await session.get(FieldModel, job.field_id) if job else None
            if not job or not field:
                return
            field_id, geometry, crop = field.id, field.geometry, field.crop

        provider = EarthEngineProvider()
        if not provider.configured:
            raise RuntimeError("Google Earth Engine не настроен на сервере")
        await _update_job(job_id, 12, "Собираем Sentinel‑2, Landsat, MODIS и ERA5‑Land")
        dataset, profile = await asyncio.wait_for(
            asyncio.to_thread(provider.collect_model_dataset, geometry, field_id, crop),
            timeout=900,
        )
        await _update_job(job_id, 72, "Восстанавливаем пропуски primary_ndvi")
        adapter = load_analysis_adapter()
        restored = adapter.restore(dataset)
        await _update_job(job_id, 86, "Ищем и объясняем негативные периоды")
        anomalies = adapter.detect(dataset)
        current_year = int(restored["date"].dt.year.max())
        points = _timeseries_points(restored, current_year)
        raw_scenes = profile.pop("scene_catalog", [])
        scenes = [
            {
                **scene,
                "id": f"{field_id}-{scene['satellite']}-{scene['date']}",
            }
            for scene in raw_scenes
        ] or _scene_records(restored, field_id)
        observed = restored[restored["primary_ndvi"].notna()].sort_values("date")
        if observed.empty:
            raise RuntimeError("Спутниковые источники не вернули ни одного валидного NDVI")
        latest = observed.iloc[-1]
        latest_climate = _number(latest["ndvi_climatology_mean"])
        delta = None if latest_climate is None or abs(latest_climate) < 0.02 else 100 * (float(latest["primary_ndvi"]) - latest_climate) / abs(latest_climate)
        current_events = [event for event in anomalies if event["start"].startswith(str(current_year))]
        status = "critical" if any(event["severity"] == "critical" for event in current_events) else "warning" if current_events else "normal"

        await _update_job(job_id, 94, "Сохраняем реальные наблюдения")
        async with SessionLocal() as session:
            job = await session.get(AnalysisJobModel, job_id)
            field = await session.get(FieldModel, field_id)
            if not job or not field:
                return
            await session.execute(delete(FieldObservationModel).where(FieldObservationModel.field_id == field_id))
            rows: list[FieldObservationModel] = []
            for row in restored.itertuples(index=False):
                valid = _first_number(row, ("s2_valid_pixels", "landsat_valid_pixels", "modis_valid_pixels"))
                cloud = _first_number(row, ("s2_cloud_cover", "landsat_cloud_cover"))
                rows.append(FieldObservationModel(
                    field_id=field_id,
                    date=pd.Timestamp(row.date).date(),
                    s2_ndvi=_number(row.s2_ndvi), s2_evi=_number(row.s2_evi), s2_ndwi=_number(row.s2_ndwi),
                    landsat_ndvi=_number(row.landsat_ndvi), landsat_evi=_number(row.landsat_evi), landsat_ndwi=_number(row.landsat_ndwi),
                    modis_ndvi=_number(row.modis_ndvi), modis_evi=_number(row.modis_evi),
                    era5_temp_c=_number(row.era5_temp_c), era5_precip_mm=_number(row.era5_precip_mm),
                    primary_ndvi=_number(row.primary_ndvi), primary_ndvi_pred=float(row.primary_ndvi_pred),
                    prediction_uncertainty=_number(row.prediction_uncertainty),
                    climate_mean=_number(row.ndvi_climatology_mean), climate_std=_number(row.ndvi_climatology_std),
                    n_reference_years=int(row.n_reference_years), valid_pixels=valid, cloud_cover=cloud,
                    is_imputed=pd.isna(row.primary_ndvi),
                ))
            session.add_all(rows)
            latest_date = pd.Timestamp(latest["date"])
            weather_rows = restored[restored["era5_temp_c"].notna()].sort_values("date")
            latest_weather = weather_rows.iloc[-1] if not weather_rows.empty else None
            latest_weather_date = pd.Timestamp(latest_weather["date"]) if latest_weather is not None else None
            seven_day = (
                restored[restored["date"].between(latest_weather_date - pd.Timedelta(days=6), latest_weather_date)]["era5_precip_mm"].sum(min_count=1)
                if latest_weather_date is not None
                else None
            )
            field.analysis_data = {
                "timeseries": points,
                "timeseries_mode": "live_multisource",
                "anomalies": anomalies,
                "scenes": scenes,
                "provider": "gee",
                "model_version": adapter.version,
                "profile": profile,
                "dataset_rows": len(restored),
                "temperature_c": _number(latest_weather["era5_temp_c"]) if latest_weather is not None else None,
                "precipitation_7d_mm": _number(seven_day),
                "delta_percent": round(delta, 1) if delta is not None else None,
                "scene_date": latest_date.strftime("%Y-%m-%d"),
                "weather_date": latest_weather_date.strftime("%Y-%m-%d") if latest_weather_date is not None else None,
                "cloud_cover": _number(latest.get("s2_cloud_cover", latest.get("landsat_cloud_cover"))),
            }
            field.ndvi = round(float(latest["primary_ndvi"]), 3)
            field.delta = round(delta, 1) if delta is not None else 0.0
            field.status = status
            field.valid_pixels = round(_number(latest.get("s2_valid_pixels", latest.get("landsat_valid_pixels", latest.get("modis_valid_pixels")))) or 0)
            field.updated_at = datetime.now(timezone.utc)
            job.status = "completed"
            job.stage = "Анализ реальных данных готов"
            job.progress = 100
            job.provider = "gee"
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()
    except Exception as error:
        async with SessionLocal() as session:
            job = await session.get(AnalysisJobModel, job_id)
            if job:
                job.status = "failed"
                job.stage = "Анализ не выполнен"
                job.error = f"{type(error).__name__}: {error}"
                await session.commit()


async def seed_database() -> None:
    """Добавляет только один проверяемый реальный контур, без вымышленных показателей."""
    async with SessionLocal() as session:
        # Старые демонстрационные поля и сгенерированные результаты не должны
        # переживать обновление приложения как будто это реальные наблюдения.
        await session.execute(delete(FieldModel).where(FieldModel.source == "demo"))
        existing = (await session.execute(select(FieldModel))).scalars().all()
        for item in existing:
            analysis = item.analysis_data or {}
            if analysis.get("provider") == "demo" or analysis.get("timeseries_mode") == "baseline_with_live_observation":
                item.analysis_data = None
                item.ndvi = 0.0
                item.delta = 0.0
                item.valid_pixels = 0
                item.status = "normal"
        field = await session.get(FieldModel, VERIFIED_FIELD["id"])
        if field is None:
            session.add(FieldModel(**VERIFIED_FIELD, geom=spatial_geometry(VERIFIED_FIELD["geometry"])))
        await session.commit()
