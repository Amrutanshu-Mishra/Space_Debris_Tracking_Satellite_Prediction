"""SQLAlchemy 2.0 models and async session management for PRAHARI.

Mirroring contracts/schemas/*.schema.json strictly:
- objects table <-> CatalogObject
- conjunctions table <-> ConjunctionEvent
- catalog_status table <-> CatalogStatus

No probability_of_collision or pc fields are permitted anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from prahari_orbital.models import (
    CatalogObject,
    CatalogStatus,
    ConjunctionEvent,
    EpochAgeDistribution,
    ObjectRef,
    ObjectType,
    RcsSize,
    RiskTier,
)
from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


# PostgreSQL supports JSONB; SQLite supports JSON
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class ObjectModel(Base):
    __tablename__ = "objects"

    norad_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tle_line1: Mapped[str] = mapped_column(String(69), nullable=False)
    tle_line2: Mapped[str] = mapped_column(String(69), nullable=False)
    epoch: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    epoch_age_hours: Mapped[float] = mapped_column(Float, nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rcs_size: Mapped[str] = mapped_column(String(32), nullable=False)
    radius_m: Mapped[float] = mapped_column(Float, nullable=False)
    perigee_km: Mapped[float] = mapped_column(Float, nullable=False)
    apogee_km: Mapped[float] = mapped_column(Float, nullable=False)
    inclination_deg: Mapped[float] = mapped_column(Float, nullable=False)


class ConjunctionModel(Base):
    __tablename__ = "conjunctions"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    primary_norad_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    primary_name: Mapped[str] = mapped_column(String(255), nullable=False)
    secondary_norad_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    secondary_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tca: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    miss_distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    relative_velocity_km_s: Mapped[float] = mapped_column(Float, nullable=False)
    radial_km: Mapped[float] = mapped_column(Float, nullable=False)
    in_track_km: Mapped[float] = mapped_column(Float, nullable=False)
    cross_track_km: Mapped[float] = mapped_column(Float, nullable=False)
    combined_radius_m: Mapped[float] = mapped_column(Float, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_note: Mapped[str] = mapped_column(Text, nullable=False)
    max_epoch_age_hours: Mapped[float] = mapped_column(Float, nullable=False)
    screened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogStatusModel(Base):
    __tablename__ = "catalog_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    object_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_refresh: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_refresh: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    epoch_age_hours: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    screening_window_hours: Mapped[float] = mapped_column(Float, nullable=False)
    last_screen_duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    pairs_considered: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pairs_fine_screened: Mapped[int] = mapped_column(Integer, nullable=False)
    events_found: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True
    )


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def model_to_catalog_object(m: ObjectModel) -> CatalogObject:
    return CatalogObject(
        norad_id=m.norad_id,
        name=m.name,
        tle_line1=m.tle_line1,
        tle_line2=m.tle_line2,
        epoch=_ensure_utc(m.epoch),
        epoch_age_hours=m.epoch_age_hours,
        object_type=ObjectType(m.object_type),
        rcs_size=RcsSize(m.rcs_size),
        radius_m=m.radius_m,
        perigee_km=m.perigee_km,
        apogee_km=m.apogee_km,
        inclination_deg=m.inclination_deg,
    )


def catalog_object_to_dict(obj: CatalogObject) -> dict[str, Any]:
    return {
        "norad_id": obj.norad_id,
        "name": obj.name,
        "tle_line1": obj.tle_line1,
        "tle_line2": obj.tle_line2,
        "epoch": _ensure_utc(obj.epoch),
        "epoch_age_hours": obj.epoch_age_hours,
        "object_type": obj.object_type.value,
        "rcs_size": obj.rcs_size.value,
        "radius_m": obj.radius_m,
        "perigee_km": obj.perigee_km,
        "apogee_km": obj.apogee_km,
        "inclination_deg": obj.inclination_deg,
    }


def model_to_conjunction_event(m: ConjunctionModel) -> ConjunctionEvent:
    return ConjunctionEvent(
        event_id=m.event_id,
        primary=ObjectRef(norad_id=m.primary_norad_id, name=m.primary_name),
        secondary=ObjectRef(norad_id=m.secondary_norad_id, name=m.secondary_name),
        tca=_ensure_utc(m.tca),
        miss_distance_km=m.miss_distance_km,
        relative_velocity_km_s=m.relative_velocity_km_s,
        radial_km=m.radial_km,
        in_track_km=m.in_track_km,
        cross_track_km=m.cross_track_km,
        combined_radius_m=m.combined_radius_m,
        risk_score=m.risk_score,
        risk_tier=RiskTier(m.risk_tier),
        confidence=m.confidence,
        confidence_note=m.confidence_note,
        max_epoch_age_hours=m.max_epoch_age_hours,
        screened_at=_ensure_utc(m.screened_at),
    )


def conjunction_event_to_dict(e: ConjunctionEvent) -> dict[str, Any]:
    return {
        "event_id": e.event_id,
        "primary_norad_id": e.primary.norad_id,
        "primary_name": e.primary.name,
        "secondary_norad_id": e.secondary.norad_id,
        "secondary_name": e.secondary.name,
        "tca": _ensure_utc(e.tca),
        "miss_distance_km": e.miss_distance_km,
        "relative_velocity_km_s": e.relative_velocity_km_s,
        "radial_km": e.radial_km,
        "in_track_km": e.in_track_km,
        "cross_track_km": e.cross_track_km,
        "combined_radius_m": e.combined_radius_m,
        "risk_score": e.risk_score,
        "risk_tier": e.risk_tier.value,
        "confidence": e.confidence,
        "confidence_note": e.confidence_note,
        "max_epoch_age_hours": e.max_epoch_age_hours,
        "screened_at": _ensure_utc(e.screened_at),
    }


def model_to_catalog_status(m: CatalogStatusModel) -> CatalogStatus:
    return CatalogStatus(
        object_count=m.object_count,
        last_refresh=_ensure_utc(m.last_refresh),
        next_refresh=_ensure_utc(m.next_refresh),
        source=m.source,
        epoch_age_hours=EpochAgeDistribution.model_validate(m.epoch_age_hours),
        screening_window_hours=m.screening_window_hours,
        last_screen_duration_s=m.last_screen_duration_s,
        pairs_considered=m.pairs_considered,
        pairs_fine_screened=m.pairs_fine_screened,
        events_found=m.events_found,
    )


def catalog_status_to_dict(s: CatalogStatus) -> dict[str, Any]:
    return {
        "object_count": s.object_count,
        "last_refresh": _ensure_utc(s.last_refresh),
        "next_refresh": _ensure_utc(s.next_refresh),
        "source": s.source,
        "epoch_age_hours": s.epoch_age_hours.model_dump(),
        "screening_window_hours": s.screening_window_hours,
        "last_screen_duration_s": s.last_screen_duration_s,
        "pairs_considered": s.pairs_considered,
        "pairs_fine_screened": s.pairs_fine_screened,
        "events_found": s.events_found,
        "created_at": datetime.now(UTC),
    }


def create_db_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, echo=False)


def create_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """Create tables if they don't already exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

