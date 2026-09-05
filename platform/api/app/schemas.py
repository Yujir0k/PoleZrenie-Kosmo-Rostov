from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Position = tuple[float, float]


class PolygonGeometry(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[Position]]

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, value: list[list[Position]]) -> list[list[Position]]:
        if not value or len(value[0]) < 4:
            raise ValueError("Полигон должен содержать минимум три вершины и замыкающую точку")
        if len(value[0]) > 501:
            raise ValueError("Полигон не может содержать больше 500 вершин")
        return value


class FieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    crop: str = Field(default="Культура не указана", max_length=120)
    region: str = Field(default="Не указан", max_length=160)
    source: Literal["osm", "drawn"] = "drawn"
    geometry: PolygonGeometry


class FieldPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    crop: str | None = Field(default=None, max_length=120)


class FieldResponse(BaseModel):
    id: str
    name: str
    crop: str
    region: str
    area_ha: float
    ndvi: float | None
    delta: float | None
    status: str
    source: str
    geometry: dict
    valid_pixels: int | None
    temperature_c: float | None = None
    precipitation_7d_mm: float | None = None
    data_provider: str | None = None
    scene_date: str | None = None
    weather_date: str | None = None
    cloud_cover: float | None = None
    worldcover_cropland_percent: float | None = None
    is_verified_cropland: bool | None = None
    dataset_rows: int | None = None
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class MapNoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    text: str | None = Field(default=None, max_length=2_000)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    field_id: str | None = Field(default=None, max_length=64)


class MapNoteResponse(BaseModel):
    id: str
    title: str
    text: str | None
    longitude: float
    latitude: float
    field_id: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


AlertLifecycleState = Literal["detected", "assigned", "verified", "confirmed", "rejected", "closed"]


class AlertWorkflowPatch(BaseModel):
    state: AlertLifecycleState
    assignee: str | None = Field(default=None, max_length=160)
    note: str | None = Field(default=None, max_length=2_000)


class AlertWorkflowResponse(BaseModel):
    id: str
    field_id: str
    state: AlertLifecycleState
    assignee: str | None
    note: str | None
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class InspectionPointCreate(BaseModel):
    field_id: str = Field(max_length=64)
    alert_id: str | None = Field(default=None, max_length=160)
    title: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=2_000)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class InspectionPointPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    status: Literal["planned", "visited", "confirmed", "rejected"] | None = None
    note: str | None = Field(default=None, max_length=2_000)


class InspectionPointResponse(BaseModel):
    id: str
    field_id: str
    alert_id: str | None
    title: str
    note: str | None
    longitude: float
    latitude: float
    status: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class JobCreate(BaseModel):
    field_id: str


class JobResponse(BaseModel):
    id: str
    field_id: str
    status: str
    stage: str
    progress: int
    provider: str
    error: str | None = None
    model_config = ConfigDict(from_attributes=True)


class RegionResult(BaseModel):
    id: str
    name: str
    display_name: str
    lat: float
    lon: float
    bounding_box: list[float]


class ProviderResponse(BaseModel):
    id: str
    name: str
    status: Literal["connected", "unavailable"]
    role: str
    datasets: list[str]
    detail: str


class SubmissionRow(BaseModel):
    anon_polygon_id: str
    date: date
    primary_ndvi_pred: float


class AIHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


class AIChatRequest(BaseModel):
    field_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=8_000)
    history: list[AIHistoryMessage] = Field(default_factory=list, max_length=12)


class AIReportRequest(BaseModel):
    field_id: str = Field(min_length=1, max_length=64)
    request: str = Field(
        default="Подготовь полный отчёт о состоянии поля и план действий агронома.",
        min_length=1,
        max_length=8_000,
    )


class AIVisionRequest(BaseModel):
    field_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=4_000)
    image_data_url: str = Field(min_length=32, max_length=8_000_000)
