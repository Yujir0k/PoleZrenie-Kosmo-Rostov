from datetime import date, datetime, timezone
from uuid import uuid4

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class FieldModel(Base):
    __tablename__ = "fields"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(160))
    crop: Mapped[str] = mapped_column(String(120), default="Культура не указана")
    region: Mapped[str] = mapped_column(String(160), default="Не указан")
    area_ha: Mapped[float] = mapped_column(Float)
    ndvi: Mapped[float] = mapped_column(Float, default=0.0)
    delta: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(24), default="normal")
    source: Mapped[str] = mapped_column(String(24), default="drawn")
    geometry: Mapped[dict] = mapped_column(JSON)
    # GeoJSON остаётся публичным контрактом API, а эта колонка даёт PostGIS
    # пространственный индекс и нормализованную MultiPolygon-геометрию.
    geom: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True).with_variant(JSON(), "sqlite"),
        nullable=True,
    )
    valid_pixels: Mapped[int] = mapped_column(Integer, default=0)
    analysis_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MapNoteModel(Base):
    __tablename__ = "map_notes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    field_id: Mapped[str | None] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    longitude: Mapped[float] = mapped_column(Float)
    latitude: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertWorkflowModel(Base):
    __tablename__ = "alert_workflows"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String(24), default="detected")
    assignee: Mapped[str | None] = mapped_column(String(160), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class InspectionPointModel(Base):
    __tablename__ = "inspection_points"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), index=True)
    alert_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    longitude: Mapped[float] = mapped_column(Float)
    latitude: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AnalysisJobModel(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    stage: Mapped[str] = mapped_column(String(160), default="Задача поставлена в очередь")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str] = mapped_column(String(32), default="gee")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FieldObservationModel(Base):
    __tablename__ = "field_observations"
    __table_args__ = (UniqueConstraint("field_id", "date", name="uq_field_observation_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    s2_ndvi: Mapped[float | None] = mapped_column(Float, nullable=True)
    s2_evi: Mapped[float | None] = mapped_column(Float, nullable=True)
    s2_ndwi: Mapped[float | None] = mapped_column(Float, nullable=True)
    landsat_ndvi: Mapped[float | None] = mapped_column(Float, nullable=True)
    landsat_evi: Mapped[float | None] = mapped_column(Float, nullable=True)
    landsat_ndwi: Mapped[float | None] = mapped_column(Float, nullable=True)
    modis_ndvi: Mapped[float | None] = mapped_column(Float, nullable=True)
    modis_evi: Mapped[float | None] = mapped_column(Float, nullable=True)
    era5_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    era5_precip_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    primary_ndvi: Mapped[float | None] = mapped_column(Float, nullable=True)
    primary_ndvi_pred: Mapped[float] = mapped_column(Float)
    prediction_uncertainty: Mapped[float | None] = mapped_column(Float, nullable=True)
    climate_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    climate_std: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_reference_years: Mapped[int] = mapped_column(Integer, default=0)
    valid_pixels: Mapped[float | None] = mapped_column(Float, nullable=True)
    cloud_cover: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_imputed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
