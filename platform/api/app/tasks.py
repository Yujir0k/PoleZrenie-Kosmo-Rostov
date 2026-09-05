import asyncio
from datetime import date, timedelta

from sqlalchemy import select

from app.celery_app import celery_app
from app.database import SessionLocal, engine
from app.models import AnalysisJobModel, FieldModel
from app.services import run_analysis


async def _run_analysis_isolated(job_id: str) -> None:
    try:
        await run_analysis(job_id)
    finally:
        # Celery создаёт новый asyncio-цикл для каждой синхронной задачи.
        # Соединения asyncpg нужно закрыть до завершения этого цикла.
        await engine.dispose()


@celery_app.task(name="vegetation.analyse_field", autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def analyse_field(job_id: str) -> None:
    asyncio.run(_run_analysis_isolated(job_id))


async def _queue_stale_fields() -> list[str]:
    async with SessionLocal() as session:
        fields = (await session.execute(select(FieldModel))).scalars().all()
        active = (
            await session.execute(
                select(AnalysisJobModel.field_id).where(AnalysisJobModel.status.in_(["queued", "running"]))
            )
        ).scalars().all()
        active_ids = set(active)
        jobs: list[AnalysisJobModel] = []
        freshness_limit = date.today() - timedelta(days=1)
        for field in fields:
            scene_date = (field.analysis_data or {}).get("scene_date")
            is_fresh = False
            if scene_date:
                try:
                    is_fresh = date.fromisoformat(scene_date) >= freshness_limit
                except ValueError:
                    is_fresh = False
            if field.id in active_ids or is_fresh:
                continue
            job = AnalysisJobModel(field_id=field.id, provider="gee")
            session.add(job)
            jobs.append(job)
        await session.commit()
        return [job.id for job in jobs]


@celery_app.task(name="vegetation.refresh_all_fields")
def refresh_all_fields() -> dict:
    async def queue_isolated() -> list[str]:
        try:
            return await _queue_stale_fields()
        finally:
            await engine.dispose()

    job_ids = asyncio.run(queue_isolated())
    for job_id in job_ids:
        analyse_field.delay(job_id)
    return {"queued": len(job_ids), "job_ids": job_ids}
