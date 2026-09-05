from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки берутся из окружения и никогда не передаются в браузер."""

    app_name: str = "Мониторинг вегетации API"
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./data/vegetation.db"
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    use_celery: bool = False
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"
    tile_cache_url: str = "redis://redis:6379/2"
    tile_cache_ttl_seconds: int = 9_000
    gee_project: str | None = None
    gee_service_account_file: Path | None = None
    cdse_client_id: str | None = None
    cdse_client_secret: str | None = None
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    overpass_fallback_urls: str = "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
    external_timeout_seconds: float = 25.0
    analysis_adapter: str = "app.analysis:PoleZrenieAnalysisAdapter"
    history_years: int = 6
    yandex_api_key: str | None = None
    yandex_folder_id: str | None = None
    yandex_ai_base_url: str = "https://ai.api.cloud.yandex.net/v1"
    yandex_chat_model: str = "aliceai-llm-flash"
    yandex_report_model: str = "yandexgpt-5.1"
    yandex_vision_model: str = "qwen3.6-35b-a3b"
    yandex_ai_timeout_seconds: float = 55.0
    yandex_ai_disable_logging: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
