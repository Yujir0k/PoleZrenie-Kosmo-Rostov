from celery import Celery
from celery.schedules import crontab

from app.config import get_settings


settings = get_settings()
celery_app = Celery(
    "vegetation",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks"],
)
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"], timezone="Europe/Moscow", enable_utc=True)
celery_app.conf.beat_schedule = {
    "daily-real-data-refresh": {
        "task": "vegetation.refresh_all_fields",
        "schedule": crontab(hour=5, minute=30),
    }
}
