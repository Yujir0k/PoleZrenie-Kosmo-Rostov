import asyncio

import httpx
import pytest

from app.ai_service import (
    AIUpstreamError,
    YandexAI,
    _compact_report_context,
    build_visualizations,
    execute_tool,
)
from app.config import Settings


def sample_context():
    return {
        "field": {
            "id": "field-1",
            "name": "Тестовое поле",
            "region": "Ростовская область",
            "area_ha": 12.4,
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[40.0, 47.0], [40.1, 47.0], [40.1, 47.1], [40.0, 47.0]]],
            },
        },
        "summary": {"observations": 2},
        "timeseries": [
            {
                "date": "2026-08-01",
                "ndvi_observed": 0.65,
                "ndvi_restored": 0.65,
                "ndvi_normal": 0.7,
                "is_restored": False,
            },
            {
                "date": "2026-09-01",
                "ndvi_observed": None,
                "ndvi_restored": 0.52,
                "ndvi_normal": 0.68,
                "is_restored": True,
            },
        ],
        "risk": {"risk_state": "early_risk"},
        "anomalies": [],
        "inspection_points": [],
    }


def test_ai_is_disabled_without_server_credentials():
    client = YandexAI(
        Settings(
            _env_file=None,
            yandex_api_key=None,
            yandex_folder_id=None,
        )
    )
    assert client.configured is False


def test_field_tools_are_scoped_to_preloaded_context():
    context = sample_context()
    overview = execute_tool("get_field_overview", {}, context)
    risk = execute_tool("get_field_risk", {}, context)
    assert overview["field"]["id"] == "field-1"
    assert risk["risk_state"] == "early_risk"


def test_report_visuals_use_real_series_and_geometry():
    visualizations = build_visualizations(sample_context())
    assert [item["kind"] for item in visualizations] == ["ndvi_chart", "field_contour"]
    assert visualizations[0]["data"][-1]["value"] == 0.52
    assert visualizations[0]["data"][-1]["restored"] is True


def test_report_context_is_compact_and_does_not_send_geometry():
    context = sample_context()
    context["timeseries"] = context["timeseries"] * 100
    compact = _compact_report_context(context)

    assert "geometry" not in compact["field"]
    assert len(compact["timeseries"]) <= 120


def test_report_uses_flash_when_primary_model_is_temporarily_unavailable(monkeypatch):
    client = YandexAI(
        Settings(
            _env_file=None,
            yandex_api_key="secret",
            yandex_folder_id="folder",
            yandex_report_model="yandexgpt-5.1",
            yandex_chat_model="aliceai-llm-flash",
        )
    )
    calls = []

    async def fake_response(payload, timeout_seconds=None):
        calls.append((payload["model"], timeout_seconds))
        if len(calls) == 1:
            raise AIUpstreamError("temporary")
        return {"output_text": "## Краткий вывод\nРезервный отчёт"}

    monkeypatch.setattr(client, "_response", fake_response)
    result = asyncio.run(client.report("Составь отчёт", sample_context()))

    assert result["model"] == "aliceai-llm-flash"
    assert "fallback_model" in result["used_tools"]
    assert calls[0][0].endswith("/yandexgpt-5.1")
    assert calls[1][0].endswith("/aliceai-llm-flash")


def test_report_returns_grounded_local_summary_when_yandex_is_down(monkeypatch):
    client = YandexAI(
        Settings(
            _env_file=None,
            yandex_api_key="secret",
            yandex_folder_id="folder",
        )
    )

    async def unavailable(*args, **kwargs):
        raise AIUpstreamError("temporary")

    monkeypatch.setattr(client, "_response", unavailable)
    result = asyncio.run(client.report("Составь отчёт", sample_context()))

    assert result["model"] == "local-field-summary"
    assert "local_fallback" in result["used_tools"]
    assert "## Ограничения данных" in result["message"]
    assert "внешний AI-сервис временно недоступен" in result["message"]


def test_unknown_folder_error_is_safe_and_actionable(monkeypatch):
    settings = Settings(
        _env_file=None,
        yandex_api_key="secret",
        yandex_folder_id="wrong-folder",
    )
    client = YandexAI(settings)

    async def fake_post(*args, **kwargs):
        return httpx.Response(
            400,
            json={"detail": "Unknown folder wrong-folder"},
            request=httpx.Request("POST", "https://example.test/v1/responses"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(AIUpstreamError, match="ID каталога AI Studio") as raised:
        asyncio.run(client._response({"model": "test"}))
    assert "wrong-folder" not in str(raised.value)


def test_embedded_responses_error_is_not_treated_as_success(monkeypatch):
    settings = Settings(
        _env_file=None,
        yandex_api_key="secret",
        yandex_folder_id="folder",
    )
    client = YandexAI(settings)

    async def fake_post(*args, **kwargs):
        return httpx.Response(
            200,
            json={"status": "failed", "error": {"code": "model_call_error", "message": "Model failed"}},
            request=httpx.Request("POST", "https://example.test/v1/responses"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(AIUpstreamError, match="Model failed"):
        asyncio.run(client._response({"model": "test"}))


def test_vision_uses_yandex_chat_completions_shape(monkeypatch):
    settings = Settings(
        _env_file=None,
        yandex_api_key="secret",
        yandex_folder_id="folder",
    )
    client = YandexAI(settings)
    captured = {}

    async def fake_post(_client, url, **kwargs):
        captured["url"] = url
        captured["payload"] = kwargs["json"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Видно поле"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = asyncio.run(
        client.vision(
            "Что видно?",
            "data:image/png;base64,AAAA",
            sample_context(),
        )
    )

    assert captured["url"].endswith("/chat/completions")
    assert captured["payload"]["messages"][1]["content"][1]["type"] == "image_url"
    assert result["message"] == "Видно поле"
