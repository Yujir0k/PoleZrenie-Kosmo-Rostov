from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import FieldModel, FieldObservationModel, InspectionPointModel, MapNoteModel
from app.risk import build_risk_profile


SYSTEM_INSTRUCTIONS = """Ты — AI-помощник агронома в системе «ПолеЗрение».
Работай только с данными выбранного поля, полученными через доступные функции.
Не придумывай измерения, диагнозы и причинно-следственные связи. Если данных недостаточно,
прямо скажи об этом. Разделяй факт, гипотезу и рекомендацию. Пиши понятно по-русски,
расшифровывай NDVI, NDWI, EVI и z-score при первом упоминании. Для опасных или затратных
действий рекомендуй подтверждение специалистом и полевой осмотр. Всегда указывай даты
наблюдений и качество данных, когда они доступны. Не называй восстановленные значения
спутниковыми измерениями и не используй будущие данные."""

REPORT_INSTRUCTIONS = SYSTEM_INSTRUCTIONS + """

Составь аккуратный агрономический отчёт в Markdown. Используй разделы:
## Краткий вывод
## Что видно в данных
## Возможные причины
## Что проверить на поле
## План действий
## Ограничения данных
Не повторяй одни и те же цифры. Не назначай препараты, нормы внесения или химическую
обработку без сведений о культуре, фазе развития, регионе и очного подтверждения причины."""


class AIConfigurationError(RuntimeError):
    pass


class AIUpstreamError(RuntimeError):
    pass


def _round(value: float | None, digits: int = 3) -> float | None:
    return round(float(value), digits) if value is not None else None


async def load_field_context(session: AsyncSession, field_id: str) -> dict[str, Any] | None:
    field = await session.get(FieldModel, field_id)
    if field is None:
        return None
    observations = (
        await session.execute(
            select(FieldObservationModel)
            .where(FieldObservationModel.field_id == field_id)
            .order_by(FieldObservationModel.date)
        )
    ).scalars().all()
    inspections = (
        await session.execute(
            select(InspectionPointModel)
            .where(InspectionPointModel.field_id == field_id)
            .order_by(InspectionPointModel.created_at.desc())
        )
    ).scalars().all()
    notes = (
        await session.execute(
            select(MapNoteModel)
            .where(MapNoteModel.field_id == field_id)
            .order_by(MapNoteModel.created_at.desc())
        )
    ).scalars().all()
    analysis = field.analysis_data or {}
    risk = build_risk_profile(observations, field.area_ha, None)
    signal = risk.get("signal")
    if signal:
        signal = {**signal, "id": f"{field.id}-{signal['as_of'][:4]}-risk"}

    series = [
        {
            "date": row.date.isoformat(),
            "ndvi_observed": _round(row.primary_ndvi),
            "ndvi_restored": _round(row.primary_ndvi_pred),
            "ndvi_normal": _round(row.climate_mean),
            "ndwi": _round(row.s2_ndwi),
            "evi": _round(row.s2_evi),
            "temperature_c": _round(row.era5_temp_c, 1),
            "precipitation_mm": _round(row.era5_precip_mm, 1),
            "valid_pixels": _round(row.valid_pixels, 1),
            "cloud_cover": _round(row.cloud_cover, 1),
            "is_restored": bool(row.is_imputed or row.primary_ndvi is None),
        }
        for row in observations
    ]
    latest = series[-1] if series else None
    observed_values = [item["ndvi_observed"] for item in series if item["ndvi_observed"] is not None]
    summary = {
        "observations": len(series),
        "first_date": series[0]["date"] if series else None,
        "last_date": series[-1]["date"] if series else None,
        "latest": latest,
        "ndvi_min": min(observed_values) if observed_values else None,
        "ndvi_max": max(observed_values) if observed_values else None,
        "reference_seasons": max((row.n_reference_years for row in observations), default=0),
    }
    return {
        "field": {
            "id": field.id,
            "name": field.name,
            "crop": field.crop,
            "region": field.region,
            "area_ha": _round(field.area_ha, 1),
            "status": field.status,
            "source": field.source,
            "data_provider": analysis.get("provider"),
            "scene_date": analysis.get("scene_date"),
            "geometry": field.geometry,
        },
        "summary": summary,
        "timeseries": series,
        "risk": signal,
        "anomalies": analysis.get("anomalies", []),
        "scenes": analysis.get("scenes", [])[-24:],
        "inspection_points": [
            {
                "id": point.id,
                "title": point.title,
                "note": point.note,
                "status": point.status,
                "longitude": point.longitude,
                "latitude": point.latitude,
                "updated_at": point.updated_at.isoformat(),
            }
            for point in inspections
        ],
        "map_notes": [
            {
                "title": note.title,
                "text": note.text,
                "longitude": note.longitude,
                "latitude": note.latitude,
                "created_at": note.created_at.isoformat(),
            }
            for note in notes
        ],
    }


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_field_overview",
        "description": "Получить паспорт выбранного поля, последнюю дату, сводные показатели и источник данных.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_field_timeseries",
        "description": "Получить фактический и восстановленный NDVI, норму, NDWI, EVI и погоду за последние дни.",
        "parameters": {
            "type": "object",
            "properties": {
                "period_days": {"type": "integer", "minimum": 14, "maximum": 730, "description": "Глубина периода в днях"}
            },
            "required": ["period_days"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_field_risk",
        "description": "Получить текущий ранний сигнал, доказательства, гипотезу, уверенность и рекомендуемое действие.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_field_anomalies",
        "description": "Получить найденные системой периоды аномалий выбранного поля.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_inspection_points",
        "description": "Получить точки полевого осмотра, их координаты, заметки и статусы.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
]


def execute_tool(name: str, arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    if name == "get_field_overview":
        return {"field": context["field"], "summary": context["summary"]}
    if name == "get_field_timeseries":
        days = max(14, min(730, int(arguments.get("period_days", 120))))
        series = context["timeseries"]
        if not series:
            return {"points": [], "state": "not_analyzed"}
        cutoff = date.fromisoformat(series[-1]["date"]).toordinal() - days
        return {"points": [item for item in series if date.fromisoformat(item["date"]).toordinal() >= cutoff]}
    if name == "get_field_risk":
        return context["risk"] or {"state": "no_signal"}
    if name == "get_field_anomalies":
        return {"events": context["anomalies"]}
    if name == "get_inspection_points":
        return {"points": context["inspection_points"]}
    return {"error": "Неизвестный инструмент"}


def _extract_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()
    chunks: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def _compact_report_context(context: dict[str, Any]) -> dict[str, Any]:
    """Keep the report grounded while avoiding an unnecessarily heavy prompt."""
    series = context.get("timeseries", [])
    if len(series) > 120:
        step = max(1, math.ceil(len(series) / 119))
        sampled = series[::step]
        if sampled[-1] is not series[-1]:
            sampled.append(series[-1])
        series = sampled
    field = {
        key: value
        for key, value in context.get("field", {}).items()
        if key != "geometry"
    }
    return {
        "field": field,
        "summary": context.get("summary", {}),
        "risk": context.get("risk"),
        "anomalies": context.get("anomalies", [])[-20:],
        "timeseries": series,
        "inspection_points": context.get("inspection_points", [])[-30:],
        "map_notes": context.get("map_notes", [])[-30:],
        "scenes": context.get("scenes", [])[-12:],
    }


def _local_data_report(request: str, context: dict[str, Any]) -> str:
    """Last-resort factual report when the external provider is unavailable."""
    field = context.get("field", {})
    summary = context.get("summary", {})
    latest = summary.get("latest") or {}
    risk = context.get("risk") or {}
    inspections = context.get("inspection_points", [])
    notes = context.get("map_notes", [])
    observed = latest.get("ndvi_observed")
    restored = latest.get("ndvi_restored")
    ndvi = observed if observed is not None else restored
    source = "фактическое спутниковое наблюдение" if observed is not None else "оценка модели восстановления"
    risk_state = risk.get("risk_state") or "нет рассчитанного сигнала"
    risk_text = {
        "normal": "отклонение от сезонной нормы не выявлено",
        "early_risk": "обнаружен ранний сигнал; требуется наблюдение и проверка на поле",
        "anomaly": "обнаружена аномалия; приоритетен полевой осмотр",
        "insufficient_data": "данных недостаточно для надёжной оценки риска",
    }.get(risk_state, str(risk_state))
    latest_date = latest.get("date") or summary.get("last_date") or "дата недоступна"
    ndvi_text = "нет данных" if ndvi is None else f"{float(ndvi):.3f}"
    crop = field.get("crop") or "культура не указана"
    return f"""## Краткий вывод

Поле «{field.get('name', 'Без названия')}», {crop}, площадь {field.get('area_ha', '—')} га. На {latest_date} NDVI (индекс активности растительности) составляет {ndvi_text}; источник значения — {source}. Текущая оценка риска: {risk_text}.

## Что видно в данных

- Доступный период: {summary.get('first_date') or '—'} — {summary.get('last_date') or '—'}.
- Точек временного ряда: {summary.get('observations', 0)}.
- Минимальный и максимальный фактический NDVI: {summary.get('ndvi_min') if summary.get('ndvi_min') is not None else '—'} / {summary.get('ndvi_max') if summary.get('ndvi_max') is not None else '—'}.
- Сезонов в исторической базе: {summary.get('reference_seasons', 0)}.

## Возможные причины

Автоматически подтверждённую причину определить нельзя. Погодные условия, состояние почвы, вредители, болезни и агротехнические операции следует рассматривать как гипотезы только после сопоставления с осмотром и журналом работ.

## Что проверить на поле

- Осмотреть зоны с визуальными отличиями и сверить их с последним доступным снимком.
- Проверить влажность почвы, равномерность развития, признаки повреждений и болезней.
- Сопоставить наблюдения с существующими точками осмотра ({len(inspections)}) и заметками ({len(notes)}).

## План действий

1. Провести полевой осмотр при наличии раннего сигнала или видимого неоднородного участка.
2. Зафиксировать фото, координаты и краткое описание в точке осмотра.
3. После нового спутникового наблюдения проверить направление изменения NDVI.

## Ограничения данных

Этот резервный отчёт сформирован напрямую из проверенных данных поля, потому что внешний AI-сервис временно недоступен. Он не устанавливает диагноз и не рекомендует химическую обработку. Исходный запрос пользователя: «{request.strip()}».
""".strip()


@dataclass
class YandexAI:
    settings: Settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.yandex_api_key and self.settings.yandex_folder_id)

    def model_uri(self, model: str) -> str:
        return f"gpt://{self.settings.yandex_folder_id}/{model}"

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise AIConfigurationError("AI-помощник ещё не подключён: добавьте YANDEX_API_KEY и YANDEX_FOLDER_ID")
        headers = {
            "Authorization": f"Api-Key {self.settings.yandex_api_key}",
            "OpenAI-Project": str(self.settings.yandex_folder_id),
            "x-folder-id": str(self.settings.yandex_folder_id),
            "Content-Type": "application/json",
        }
        if self.settings.yandex_ai_disable_logging:
            headers["x-data-logging-enabled"] = "false"
        try:
            async with httpx.AsyncClient(
                timeout=timeout_seconds or self.settings.yandex_ai_timeout_seconds
            ) as client:
                response = await client.post(
                    f"{self.settings.yandex_ai_base_url.rstrip('/')}/{endpoint.lstrip('/')}",
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError as error:
            raise AIUpstreamError("Yandex AI Studio временно не отвечает") from error
        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {}
        embedded_error = response_payload.get("error") if isinstance(response_payload, dict) else None
        if response.is_error or embedded_error or response_payload.get("status") == "failed":
            try:
                nested_error = embedded_error or {}
                detail = (
                    nested_error.get("message")
                    or response_payload.get("detail")
                    or response_payload.get("message")
                    or response_payload.get("title")
                )
            except AttributeError:
                detail = None
            if isinstance(detail, str) and detail.lower().startswith("unknown folder"):
                detail = (
                    "Yandex AI Studio не находит указанный каталог. "
                    "Скопируйте именно ID каталога AI Studio, а не ID облака или сервисного аккаунта."
                )
            raise AIUpstreamError(detail or f"Yandex AI Studio вернул ошибку {response.status_code}")
        return response_payload

    async def _response(
        self,
        payload: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await self._post("responses", payload, timeout_seconds)

    async def _chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("chat/completions", payload)

    async def chat(self, message: str, history: list[dict[str, str]], context: dict[str, Any]) -> dict[str, Any]:
        input_items: list[dict[str, Any]] = [
            {"role": item["role"], "content": item["content"]} for item in history[-12:]
        ]
        input_items.append({"role": "user", "content": message})
        used_tools: list[str] = []
        payload: dict[str, Any] = {
            "model": self.model_uri(self.settings.yandex_chat_model),
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": input_items,
            "tools": TOOLS,
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_output_tokens": 1800,
        }
        result = await self._response(payload)
        for _ in range(3):
            calls = [item for item in result.get("output", []) if item.get("type") == "function_call"]
            if not calls:
                break
            input_items.extend(result.get("output", []))
            for call in calls:
                name = str(call.get("name", ""))
                try:
                    arguments = json.loads(call.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                tool_result = execute_tool(name, arguments, context)
                used_tools.append(name)
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.get("call_id") or call.get("id"),
                        "output": json.dumps(tool_result, ensure_ascii=False, default=str),
                    }
                )
            payload["input"] = input_items
            result = await self._response(payload)
        text = _extract_text(result)
        if not text:
            raise AIUpstreamError("Модель не сформировала текстовый ответ")
        return {"message": text, "model": self.settings.yandex_chat_model, "used_tools": list(dict.fromkeys(used_tools))}

    async def report(self, request: str, context: dict[str, Any]) -> dict[str, Any]:
        model = self.settings.yandex_report_model
        compact_context = _compact_report_context(context)
        base_payload = {
            "instructions": REPORT_INSTRUCTIONS,
            "input": (
                f"Запрос пользователя:\n{request}\n\n"
                "Проверенные данные выбранного поля в JSON:\n"
                + json.dumps(compact_context, ensure_ascii=False, default=str)
            ),
            "temperature": 0.2,
            "max_output_tokens": 3000,
        }
        try:
            result = await self._response(
                {
                    **base_payload,
                    "model": self.model_uri(model),
                },
                min(self.settings.yandex_ai_timeout_seconds, 40.0),
            )
            used_tools = ["field_context"]
        except AIUpstreamError:
            fallback_model = self.settings.yandex_chat_model
            if fallback_model == model:
                return {
                    "message": _local_data_report(request, context),
                    "model": "local-field-summary",
                    "used_tools": ["field_context", "local_fallback"],
                }
            try:
                result = await self._response(
                    {
                        **base_payload,
                        "model": self.model_uri(fallback_model),
                        "max_output_tokens": 2400,
                    },
                    min(self.settings.yandex_ai_timeout_seconds, 18.0),
                )
                model = fallback_model
                used_tools = ["field_context", "fallback_model"]
            except AIUpstreamError:
                return {
                    "message": _local_data_report(request, context),
                    "model": "local-field-summary",
                    "used_tools": ["field_context", "local_fallback"],
                }
        text = _extract_text(result)
        if not text:
            return {
                "message": _local_data_report(request, context),
                "model": "local-field-summary",
                "used_tools": ["field_context", "local_fallback"],
            }
        return {"message": text, "model": model, "used_tools": used_tools}

    async def vision(self, question: str, image_data_url: str, context: dict[str, Any]) -> dict[str, Any]:
        if not image_data_url.startswith("data:image/"):
            raise ValueError("Поддерживается изображение в формате data:image/...;base64")
        result = await self._chat_completion(
            {
                "model": self.model_uri(self.settings.yandex_vision_model),
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_INSTRUCTIONS
                        + "\nИзображение — дополнительный источник. Не делай диагноз только по цвету визуализации.",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question + "\nПаспорт поля: " + json.dumps(context["field"], ensure_ascii=False)},
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                        ],
                    }
                ],
                "temperature": 0.15,
                # Qwen otherwise spends the whole output budget on hidden reasoning
                # and may return content=null. Image description does not need CoT.
                "reasoning_effort": "none",
                "max_completion_tokens": 1800,
            }
        )
        choices = result.get("choices") or []
        text = ""
        if choices:
            text = str((choices[0].get("message") or {}).get("content") or "").strip()
        if not text:
            raise AIUpstreamError("Модель не сформировала ответ по изображению")
        return {"message": text, "model": self.settings.yandex_vision_model, "used_tools": ["image_analysis"]}


def build_visualizations(context: dict[str, Any]) -> list[dict[str, Any]]:
    points = [
        {
            "date": item["date"],
            "value": item["ndvi_observed"] if item["ndvi_observed"] is not None else item["ndvi_restored"],
            "normal": item["ndvi_normal"],
            "restored": item["is_restored"],
        }
        for item in context["timeseries"][-90:]
    ]
    artifacts: list[dict[str, Any]] = []
    if points:
        artifacts.append(
            {
                "kind": "ndvi_chart",
                "title": "Динамика NDVI",
                "subtitle": f"{points[0]['date']} — {points[-1]['date']}",
                "data": points,
            }
        )
    artifacts.append(
        {
            "kind": "field_contour",
            "title": "Контур выбранного поля",
            "subtitle": f"{context['field']['area_ha']} га · {context['field']['region']}",
            "geometry": context["field"]["geometry"],
        }
    )
    return artifacts
