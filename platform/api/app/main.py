from __future__ import annotations

import asyncio
import io
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.ai_service import AIConfigurationError, AIUpstreamError, YandexAI, build_visualizations, load_field_context
from app.database import get_session, init_database
from app.data_pipeline import MODEL_COLUMNS
from app.models import AlertWorkflowModel, AnalysisJobModel, FieldModel, FieldObservationModel, InspectionPointModel, MapNoteModel
from app.providers import CopernicusProvider, EarthEngineProvider, OpenGeoProvider
from app.risk import build_risk_profile
from app.schemas import AIChatRequest, AIReportRequest, AIVisionRequest, AlertWorkflowPatch, AlertWorkflowResponse, FieldCreate, FieldPatch, FieldResponse, InspectionPointCreate, InspectionPointPatch, InspectionPointResponse, JobCreate, JobResponse, MapNoteCreate, MapNoteResponse, ProviderResponse, RegionResult
from app.services import run_analysis, seed_database, spatial_geometry, validate_geometry
from app.tile_cache import TileDescriptorCache


settings = get_settings()
tile_cache = TileDescriptorCache(settings.tile_cache_url, settings.tile_cache_ttl_seconds)
ai_client = YandexAI(settings)
_tile_descriptor_tasks: dict[str, asyncio.Task[dict]] = {}
_tile_descriptor_tasks_lock = asyncio.Lock()


def _release_tile_descriptor_task(cache_key: str, finished: asyncio.Task[dict]) -> None:
    async def release() -> None:
        async with _tile_descriptor_tasks_lock:
            if _tile_descriptor_tasks.get(cache_key) is finished:
                _tile_descriptor_tasks.pop(cache_key, None)

    asyncio.create_task(release())


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_database()
    await seed_database()
    yield
    await tile_cache.close()


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan, docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def field_response(field: FieldModel) -> FieldResponse:
    analysis = field.analysis_data or {}
    has_analysis = analysis.get("provider") == "gee"
    return FieldResponse.model_validate(
        {
            "id": field.id,
            "name": field.name,
            "crop": field.crop,
            "region": field.region,
            "area_ha": field.area_ha,
            "ndvi": field.ndvi if has_analysis else None,
            "delta": analysis.get("delta_percent") if has_analysis else None,
            "status": field.status,
            "source": field.source,
            "geometry": field.geometry,
            "valid_pixels": field.valid_pixels if has_analysis else None,
            "temperature_c": analysis.get("temperature_c"),
            "precipitation_7d_mm": analysis.get("precipitation_7d_mm"),
            "data_provider": analysis.get("provider"),
            "scene_date": analysis.get("scene_date"),
            "weather_date": analysis.get("weather_date"),
            "cloud_cover": analysis.get("cloud_cover"),
            "worldcover_cropland_percent": (analysis.get("profile") or {}).get("worldcover_cropland_percent"),
            "is_verified_cropland": (analysis.get("profile") or {}).get("is_verified_cropland"),
            "dataset_rows": analysis.get("dataset_rows"),
            "updated_at": field.updated_at,
        }
    )


@app.get("/health")
async def health() -> dict:
    return {"status":"ok", "service":"vegetation-api", "time":datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/ai/status")
async def ai_status() -> dict:
    return {
        "configured": ai_client.configured,
        "provider": "Yandex AI Studio",
        "models": {
            "chat": settings.yandex_chat_model,
            "report": settings.yandex_report_model,
            "vision": settings.yandex_vision_model,
        },
        "data_logging": not settings.yandex_ai_disable_logging,
    }


def _raise_ai_error(error: Exception) -> None:
    if isinstance(error, AIConfigurationError):
        raise HTTPException(503, str(error)) from error
    if isinstance(error, AIUpstreamError):
        raise HTTPException(502, str(error)) from error
    raise error


@app.post("/api/v1/ai/chat")
async def ai_chat(payload: AIChatRequest, session: AsyncSession = Depends(get_session)) -> dict:
    context = await load_field_context(session, payload.field_id)
    if context is None:
        raise HTTPException(404, "Поле не найдено")
    try:
        answer = await ai_client.chat(
            payload.message,
            [item.model_dump() for item in payload.history],
            context,
        )
    except (AIConfigurationError, AIUpstreamError) as error:
        _raise_ai_error(error)
    return {**answer, "field_id": payload.field_id, "visualizations": build_visualizations(context)}


@app.post("/api/v1/ai/report")
async def ai_report(payload: AIReportRequest, session: AsyncSession = Depends(get_session)) -> dict:
    context = await load_field_context(session, payload.field_id)
    if context is None:
        raise HTTPException(404, "Поле не найдено")
    try:
        answer = await ai_client.report(payload.request, context)
    except (AIConfigurationError, AIUpstreamError) as error:
        _raise_ai_error(error)
    return {**answer, "field_id": payload.field_id, "visualizations": build_visualizations(context)}


@app.post("/api/v1/ai/vision")
async def ai_vision(payload: AIVisionRequest, session: AsyncSession = Depends(get_session)) -> dict:
    context = await load_field_context(session, payload.field_id)
    if context is None:
        raise HTTPException(404, "Поле не найдено")
    try:
        answer = await ai_client.vision(payload.question, payload.image_data_url, context)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except (AIConfigurationError, AIUpstreamError) as error:
        _raise_ai_error(error)
    return {**answer, "field_id": payload.field_id, "visualizations": build_visualizations(context)}


@app.get("/api/v1/fields", response_model=list[FieldResponse])
async def list_fields(session: AsyncSession = Depends(get_session)):
    fields = (await session.execute(select(FieldModel).order_by(FieldModel.created_at.desc()))).scalars().all()
    return [field_response(field) for field in fields]


@app.get("/api/v1/map-notes", response_model=list[MapNoteResponse])
async def list_map_notes(session: AsyncSession = Depends(get_session)):
    notes = (await session.execute(select(MapNoteModel).order_by(MapNoteModel.created_at.desc()))).scalars().all()
    return notes


@app.post("/api/v1/map-notes", response_model=MapNoteResponse, status_code=201)
async def create_map_note(payload: MapNoteCreate, session: AsyncSession = Depends(get_session)):
    if payload.field_id and not await session.get(FieldModel, payload.field_id):
        raise HTTPException(404, "Поле для метки не найдено")
    note = MapNoteModel(**payload.model_dump())
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return note


@app.delete("/api/v1/map-notes/{note_id}", status_code=204)
async def delete_map_note(note_id: str, session: AsyncSession = Depends(get_session)):
    note = await session.get(MapNoteModel, note_id)
    if not note:
        raise HTTPException(404, "Метка не найдена")
    await session.delete(note)
    await session.commit()


@app.get("/api/v1/inspection-points", response_model=list[InspectionPointResponse])
async def list_inspection_points(field_id: str | None = None, session: AsyncSession = Depends(get_session)):
    statement = select(InspectionPointModel).order_by(InspectionPointModel.created_at.desc())
    if field_id:
        statement = statement.where(InspectionPointModel.field_id == field_id)
    return (await session.execute(statement)).scalars().all()


@app.post("/api/v1/inspection-points", response_model=InspectionPointResponse, status_code=201)
async def create_inspection_point(payload: InspectionPointCreate, session: AsyncSession = Depends(get_session)):
    if not await session.get(FieldModel, payload.field_id):
        raise HTTPException(404, "Поле для точки осмотра не найдено")
    point = InspectionPointModel(**payload.model_dump())
    session.add(point)
    await session.commit()
    await session.refresh(point)
    return point


@app.patch("/api/v1/inspection-points/{point_id}", response_model=InspectionPointResponse)
async def patch_inspection_point(point_id: str, payload: InspectionPointPatch, session: AsyncSession = Depends(get_session)):
    point = await session.get(InspectionPointModel, point_id)
    if not point:
        raise HTTPException(404, "Точка осмотра не найдена")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(point, key, value)
    await session.commit()
    await session.refresh(point)
    return point


@app.delete("/api/v1/inspection-points/{point_id}", status_code=204)
async def delete_inspection_point(point_id: str, session: AsyncSession = Depends(get_session)):
    point = await session.get(InspectionPointModel, point_id)
    if not point:
        raise HTTPException(404, "Точка осмотра не найдена")
    await session.delete(point)
    await session.commit()


@app.post("/api/v1/fields", response_model=FieldResponse, status_code=201)
async def create_field(payload: FieldCreate, session: AsyncSession = Depends(get_session)):
    try:
        area_ha = validate_geometry(payload.geometry.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    geometry = payload.geometry.model_dump()
    field = FieldModel(name=payload.name, crop=payload.crop, region=payload.region, source=payload.source, geometry=geometry, geom=spatial_geometry(geometry), area_ha=area_ha)
    session.add(field)
    await session.commit()
    await session.refresh(field)
    return field_response(field)


@app.patch("/api/v1/fields/{field_id}", response_model=FieldResponse)
async def patch_field(field_id: str, payload: FieldPatch, session: AsyncSession = Depends(get_session)):
    field = await session.get(FieldModel, field_id)
    if not field:
        raise HTTPException(404, "Поле не найдено")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(field, key, value)
    await session.commit()
    await session.refresh(field)
    return field_response(field)


@app.delete("/api/v1/fields/{field_id}", status_code=204)
async def delete_field(field_id: str, session: AsyncSession = Depends(get_session)):
    field = await session.get(FieldModel, field_id)
    if not field:
        raise HTTPException(404, "Поле не найдено")
    await session.delete(field)
    await session.commit()


@app.post("/api/v1/analysis-jobs", response_model=JobResponse, status_code=202)
async def create_job(payload: JobCreate, background: BackgroundTasks, session: AsyncSession = Depends(get_session)):
    field = await session.get(FieldModel, payload.field_id)
    if not field:
        raise HTTPException(404, "Поле не найдено")
    job = AnalysisJobModel(field_id=field.id, provider="gee" if settings.gee_project else "unavailable")
    session.add(job)
    await session.commit()
    await session.refresh(job)
    if settings.use_celery:
        from app.tasks import analyse_field
        analyse_field.delay(job.id)
    else:
        background.add_task(run_analysis, job.id)
    return JobResponse.model_validate(job)


@app.get("/api/v1/analysis-jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await session.get(AnalysisJobModel, job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    return JobResponse.model_validate(job)


@app.get("/api/v1/analysis-jobs/{job_id}/events")
async def job_events(job_id: str):
    async def stream():
        last_payload = None
        while True:
            from app.database import SessionLocal
            async with SessionLocal() as session:
                job = await session.get(AnalysisJobModel, job_id)
                if not job:
                    yield "event: error\ndata: {\"message\":\"Задача не найдена\"}\n\n"
                    return
                payload = JobResponse.model_validate(job).model_dump()
            encoded = json.dumps(payload, ensure_ascii=False)
            if encoded != last_payload:
                yield f"data: {encoded}\n\n"
                last_payload = encoded
            if payload["status"] in {"completed", "failed"}:
                return
            await asyncio.sleep(0.45)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@app.get("/api/v1/fields/{field_id}/timeseries")
async def field_timeseries(field_id: str, year: int | None = Query(None, ge=2010, le=2100), session: AsyncSession = Depends(get_session)):
    field = await session.get(FieldModel, field_id)
    if not field:
        raise HTTPException(404, "Поле не найдено")
    analysis = field.analysis_data or {}
    statement = select(FieldObservationModel).where(FieldObservationModel.field_id == field_id)
    rows = (await session.execute(statement.order_by(FieldObservationModel.date))).scalars().all()
    if year is None and rows:
        year = max(row.date.year for row in rows)
    all_rows = rows
    if year is not None:
        rows = [row for row in all_rows if row.date.year == year]
    cutoff = min(datetime.now(timezone.utc).date(), date(year, 12, 31)) if year else None
    risk_profile = build_risk_profile(all_rows, field.area_ha, cutoff)
    risk_by_date = {item["date"]: item for item in risk_profile["points"]}
    points = [{
        "date":row.date.isoformat(),"observed":row.primary_ndvi,"restored":row.primary_ndvi_pred,
        "climate_mean":row.climate_mean,
        "climate_low":row.climate_mean-row.climate_std if row.climate_mean is not None and row.climate_std is not None else None,
        "climate_high":row.climate_mean+row.climate_std if row.climate_mean is not None and row.climate_std is not None else None,
        "confidence_low":max(-0.1,row.primary_ndvi_pred-(row.prediction_uncertainty or 0.05)),
        "confidence_high":min(0.95,row.primary_ndvi_pred+(row.prediction_uncertainty or 0.05)),
        "s2":row.s2_ndvi,"landsat":row.landsat_ndvi,"modis":row.modis_ndvi,
        "temperature":row.era5_temp_c,"precipitation":row.era5_precip_mm,
        "is_imputed":row.is_imputed,"valid_pixels":row.valid_pixels,"cloud_cover":row.cloud_cover,
        **risk_by_date.get(row.date.isoformat(), {}),
    } for row in rows]
    signal = risk_profile.get("signal")
    if signal:
        signal["id"] = f"{field.id}-{signal['as_of'][:4]}-risk"
    return {"field_id":field.id,"provider":analysis.get("provider"),"model_version":analysis.get("model_version"),"year":year,"points":points,"signal":signal,"state":"ready" if points else "not_analyzed"}


@app.get("/api/v1/fields/{field_id}/risk-profile")
async def field_risk_profile(
    field_id: str,
    as_of: date | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    field = await session.get(FieldModel, field_id)
    if not field:
        raise HTTPException(404, "Поле не найдено")
    rows = (
        await session.execute(
            select(FieldObservationModel)
            .where(FieldObservationModel.field_id == field_id)
            .order_by(FieldObservationModel.date)
        )
    ).scalars().all()
    profile = build_risk_profile(rows, field.area_ha, as_of)
    if profile.get("signal"):
        profile["signal"]["id"] = f"{field.id}-{profile['signal']['as_of'][:4]}-risk"
        workflow = await session.get(AlertWorkflowModel, profile["signal"]["id"])
        profile["signal"]["workflow"] = {
            "state": workflow.state if workflow else "detected",
            "assignee": workflow.assignee if workflow else None,
            "note": workflow.note if workflow else None,
        }
    return {"field_id": field.id, **profile}


@app.get("/api/v1/attention")
async def attention_queue(as_of: date | None = Query(None), session: AsyncSession = Depends(get_session)):
    fields = (await session.execute(select(FieldModel).order_by(FieldModel.name))).scalars().all()
    items: list[dict] = []
    for field in fields:
        rows = (
            await session.execute(
                select(FieldObservationModel)
                .where(FieldObservationModel.field_id == field.id)
                .order_by(FieldObservationModel.date)
            )
        ).scalars().all()
        profile = build_risk_profile(rows, field.area_ha, as_of)
        signal = profile.get("signal")
        if signal is None:
            items.append({"field_id": field.id, "field_name": field.name, "risk_state": "insufficient_data", "signal": None})
            continue
        signal["id"] = f"{field.id}-{signal['as_of'][:4]}-risk"
        workflow = await session.get(AlertWorkflowModel, signal["id"])
        signal["workflow"] = {
            "state": workflow.state if workflow else "detected",
            "assignee": workflow.assignee if workflow else None,
            "note": workflow.note if workflow else None,
        }
        items.append({"field_id": field.id, "field_name": field.name, "risk_state": signal["risk_state"], "signal": signal})
    priority = {"confirmed_anomaly": 0, "early_risk": 1, "watch": 2, "normal": 3, "insufficient_data": 4}
    items.sort(key=lambda item: (priority.get(item["risk_state"], 5), -(item.get("signal") or {}).get("risk_score", 0)))
    return {"as_of": (as_of or datetime.now(timezone.utc).date()).isoformat(), "items": items}


@app.patch("/api/v1/alerts/{alert_id}", response_model=AlertWorkflowResponse)
async def patch_alert_workflow(alert_id: str, payload: AlertWorkflowPatch, field_id: str = Query(...), session: AsyncSession = Depends(get_session)):
    if not await session.get(FieldModel, field_id):
        raise HTTPException(404, "Поле не найдено")
    workflow = await session.get(AlertWorkflowModel, alert_id)
    if workflow is None:
        workflow = AlertWorkflowModel(id=alert_id, field_id=field_id)
        session.add(workflow)
    elif workflow.field_id != field_id:
        raise HTTPException(409, "Сигнал принадлежит другому полю")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(workflow, key, value)
    await session.commit()
    await session.refresh(workflow)
    return workflow


@app.get("/api/v1/alert-validation")
async def alert_validation(session: AsyncSession = Depends(get_session)):
    reviewed = (
        await session.execute(
            select(AlertWorkflowModel).where(AlertWorkflowModel.state.in_(["confirmed", "rejected", "closed"]))
        )
    ).scalars().all()
    confirmed = sum(item.state == "confirmed" for item in reviewed)
    rejected = sum(item.state == "rejected" for item in reviewed)
    decided = confirmed + rejected
    return {
        "reviewed_alerts": len(reviewed),
        "confirmed_alerts": confirmed,
        "rejected_alerts": rejected,
        "precision": round(confirmed / decided, 3) if decided else None,
        "false_alarm_rate": round(rejected / decided, 3) if decided else None,
        "recall": None,
        "median_lead_time_days": None,
        "state": "measurable" if decided else "awaiting_field_labels",
        "limitations": [
            "Recall нельзя посчитать без разметки периодов, где проблема была, но сигнал не сработал",
            "Lead time появится после накопления подтверждённых осмотров с датой фактического начала проблемы",
        ],
    }


@app.get("/api/v1/fields/{field_id}/anomalies")
async def field_anomalies(field_id: str, session: AsyncSession = Depends(get_session)):
    field = await session.get(FieldModel, field_id)
    if not field:
        raise HTTPException(404, "Поле не найдено")
    analysis = field.analysis_data or {}
    return {"field_id":field.id,"events":analysis.get("anomalies", []),"state":"ready" if "anomalies" in analysis else "not_analyzed"}


@app.get("/api/v1/fields/{field_id}/scenes")
async def field_scenes(field_id: str, year: int | None = Query(None, ge=2010, le=2100), session: AsyncSession = Depends(get_session)):
    field = await session.get(FieldModel, field_id)
    if not field:
        raise HTTPException(404, "Поле не найдено")
    analysis = field.analysis_data or {}
    scenes = analysis.get("scenes", [])
    if year is not None:
        scenes = [scene for scene in scenes if str(scene.get("date", "")).startswith(str(year))]
    return {"field_id":field_id,"scenes":scenes,"state":"ready" if scenes else "not_analyzed"}


@app.get("/api/v1/fields/{field_id}/dataset.csv")
async def field_dataset(field_id: str, session: AsyncSession = Depends(get_session)):
    field = await session.get(FieldModel, field_id)
    if not field:
        raise HTTPException(404, "Поле не найдено")
    rows = (
        await session.execute(
            select(FieldObservationModel)
            .where(FieldObservationModel.field_id == field_id)
            .order_by(FieldObservationModel.date)
        )
    ).scalars().all()
    if not rows:
        raise HTTPException(409, "Поле ещё не проанализировано")
    data = []
    for row in rows:
        zscore = None
        if row.primary_ndvi is not None and row.climate_mean is not None and row.climate_std and row.climate_std >= 0.02:
            zscore = (row.primary_ndvi - row.climate_mean) / row.climate_std
        data.append({
            "anon_polygon_id":field_id,"date":row.date,"s2_ndvi":row.s2_ndvi,"s2_evi":row.s2_evi,"s2_ndwi":row.s2_ndwi,
            "landsat_ndvi":row.landsat_ndvi,"landsat_evi":row.landsat_evi,"landsat_ndwi":row.landsat_ndwi,
            "modis_ndvi":row.modis_ndvi,"modis_evi":row.modis_evi,"era5_temp_c":row.era5_temp_c,"era5_precip_mm":row.era5_precip_mm,
            "year":row.date.year,"primary_ndvi":row.primary_ndvi,"doy":row.date.timetuple().tm_yday,
            "ndvi_climatology_mean":row.climate_mean,"ndvi_climatology_std":row.climate_std,"ndvi_zscore":zscore,
            "n_reference_years":row.n_reference_years,"status":"critical" if zscore is not None and zscore < -2 else "warning" if zscore is not None and zscore < -1 else "normal",
            "crop_type":field.crop,"is_synthetic_gap":False,"primary_ndvi_pred":row.primary_ndvi_pred,
        })
    frame = pd.DataFrame(data)
    columns = [*MODEL_COLUMNS, "is_synthetic_gap", "primary_ndvi_pred"]
    stream = io.StringIO()
    frame[columns].to_csv(stream, index=False, date_format="%Y-%m-%d", encoding="utf-8")
    return Response(
        content=stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":f'attachment; filename="{field_id}-model-dataset.csv"'},
    )


@app.get("/api/v1/fields/{field_id}/tile-descriptor")
async def tile_descriptor(
    field_id: str,
    layer: str = Query("ndvi", pattern="^(rgb|ndvi|evi|ndwi)$"),
    scene_date: date | None = Query(None),
    satellite: str = Query("sentinel2", pattern="^(sentinel2|landsat|modis)$"),
    session: AsyncSession = Depends(get_session),
):
    field = await session.get(FieldModel, field_id)
    if not field:
        raise HTTPException(404, "Поле не найдено")
    provider = EarthEngineProvider()
    if not provider.configured:
        raise HTTPException(409, "Earth Engine не подключён: настройте GEE_PROJECT и сервисный аккаунт")
    target_date = scene_date or datetime.now(timezone.utc).date()
    start = (target_date - timedelta(days=12)).isoformat()
    end = (target_date + timedelta(days=13)).isoformat()
    satellite_label = {"sentinel2":"Sentinel‑2", "landsat":"Landsat 8/9", "modis":"MODIS"}[satellite]
    scene_metadata = next(
        (
            item for item in (field.analysis_data or {}).get("scenes", [])
            if item.get("date") == target_date.isoformat() and item.get("satellite") == satellite_label
        ),
        None,
    )
    cache_key = f"gee-tile:v2:{field_id}:{satellite}:{target_date.isoformat()}:{layer}"
    cached = await tile_cache.get(cache_key)
    if cached:
        return cached

    async def build_descriptor() -> dict:
        result = await asyncio.to_thread(
            provider.preview_descriptor,
            field.geometry,
            start,
            end,
            layer,
            target_date.isoformat(),
            satellite,
            (scene_metadata or {}).get("scene_id"),
            (scene_metadata or {}).get("date"),
            (scene_metadata or {}).get("cloud_cover"),
        )
        await tile_cache.set(cache_key, result)
        return result

    try:
        async with _tile_descriptor_tasks_lock:
            task = _tile_descriptor_tasks.get(cache_key)
            if task is None:
                task = asyncio.create_task(build_descriptor())
                _tile_descriptor_tasks[cache_key] = task
                task.add_done_callback(lambda finished: _release_tile_descriptor_task(cache_key, finished))
        return await asyncio.shield(task)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except Exception as error:
        raise HTTPException(502, f"Earth Engine не вернул слой: {type(error).__name__}") from error


@app.get("/api/v1/fields/{field_id}/spatial-risk")
async def spatial_risk(field_id: str, scene_date: date, session: AsyncSession = Depends(get_session)):
    field = await session.get(FieldModel, field_id)
    if not field:
        raise HTTPException(404, "Поле не найдено")
    rows = (
        await session.execute(
            select(FieldObservationModel)
            .where(FieldObservationModel.field_id == field_id)
            .order_by(FieldObservationModel.date)
        )
    ).scalars().all()
    profile = build_risk_profile(rows, field.area_ha, scene_date)
    reference = next((point for point in profile.get("points", []) if point["date"] == scene_date.isoformat()), None)
    threshold = (reference or {}).get("robust_q10")
    if threshold is None:
        raise HTTPException(409, "Для даты нет нормы минимум по трём прошлым сезонам")
    scene = next(
        (
            item for item in (field.analysis_data or {}).get("scenes", [])
            if item.get("date") == scene_date.isoformat() and item.get("satellite") == "Sentinel‑2" and item.get("scene_id")
        ),
        None,
    )
    if scene is None:
        raise HTTPException(409, "Для пиксельного расчёта выберите дату сцены Sentinel‑2")
    cache_key = f"gee-spatial-risk:v1:{field_id}:{scene_date.isoformat()}:{float(threshold):.4f}"
    cached = await tile_cache.get(cache_key)
    if cached:
        return cached
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                EarthEngineProvider().spatial_risk_descriptor,
                field.geometry,
                scene["scene_id"],
                scene_date.isoformat(),
                float(threshold),
            ),
            timeout=90,
        )
        await tile_cache.set(cache_key, result)
        return result
    except Exception as error:
        raise HTTPException(502, f"Не удалось рассчитать пиксельную зону: {type(error).__name__}") from error


@app.get("/api/v1/regions/search", response_model=list[RegionResult])
async def search_regions(q: str = Query(min_length=2, max_length=120)):
    try:
        return await OpenGeoProvider().search_regions(q)
    except Exception as error:
        raise HTTPException(502, "Сервис геопоиска временно недоступен") from error


@app.get("/api/v1/field-candidates")
async def field_candidates(west: float, south: float, east: float, north: float):
    try:
        features = await OpenGeoProvider().field_candidates((west, south, east, north))
        return {"type":"FeatureCollection","features":features}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except Exception as error:
        raise HTTPException(502, "Overpass API временно недоступен") from error


@app.get("/api/v1/system/providers", response_model=list[ProviderResponse])
async def provider_statuses():
    statuses = await asyncio.gather(EarthEngineProvider().health(), CopernicusProvider().health(), OpenGeoProvider().health())
    statuses.append(type(statuses[0])("era5", "ERA5‑Land", statuses[0].status, "Доступ через Google Earth Engine", ["temperature_2m", "total_precipitation_sum"], "Метеоданные"))
    return [ProviderResponse(id=item.provider_id,name=item.name,status=item.status,role=item.role,datasets=item.datasets,detail=item.detail) for item in statuses]
