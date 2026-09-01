"""Async engine / session-maker helpers and row <-> Pydantic conversion.

Everything here is a no-op unless ``DATABASE_URL`` is set. Conversions are
one-directional per call site:

- ``row_to_catalog_object`` / ``row_to_conjunction_event`` -- read path, DB
  row to frozen contract model. ``epoch_age_hours`` is computed here, never
  read from a column.
- ``catalog_object_to_row_kwargs`` / ``conjunction_event_to_row_kwargs`` --
  write path (the loader), contract model to a ``dict`` of column values.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from prahari_orbital.models import (
    CatalogObject,
    ConjunctionEvent,
    ObjectRef,
    ObjectType,
    RcsSize,
    RiskTier,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from prahari_api.db.tables import Base, ConjunctionRow, ObjectRow


def create_db_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, echo=False, future=True)


def create_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """Create tables if absent. Used by the test suite and by the first
    request in live mode; production schema management is Alembic."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def epoch_age_hours(epoch: datetime, *, now: datetime | None = None) -> float:
    """Hours between ``epoch`` and ``now`` (default: wall clock), floored at 0.

    This is the value the ``objects`` table deliberately does not store: it
    is only meaningful relative to the moment of the request.
    """
    reference = now or datetime.now(UTC)
    delta_hours = (_ensure_utc(reference) - _ensure_utc(epoch)).total_seconds() / 3600.0
    return round(max(0.0, delta_hours), 1)


def row_to_catalog_object(row: ObjectRow, *, now: datetime | None = None) -> CatalogObject:
    return CatalogObject(
        norad_id=row.norad_id,
        name=row.name,
        tle_line1=row.tle_line1,
        tle_line2=row.tle_line2,
        epoch=_ensure_utc(row.epoch),
        epoch_age_hours=epoch_age_hours(row.epoch, now=now),
        object_type=ObjectType(row.object_type),
        rcs_size=RcsSize(row.rcs_size),
        radius_m=row.radius_m,
        perigee_km=row.perigee_km,
        apogee_km=row.apogee_km,
        inclination_deg=row.inclination_deg,
    )


def row_to_conjunction_event(
    row: ConjunctionRow, *, primary_name: str, secondary_name: str
) -> ConjunctionEvent:
    return ConjunctionEvent(
        event_id=row.event_id,
        primary=ObjectRef(norad_id=row.primary_norad_id, name=primary_name),
        secondary=ObjectRef(norad_id=row.secondary_norad_id, name=secondary_name),
        tca=_ensure_utc(row.tca),
        miss_distance_km=row.miss_distance_km,
        relative_velocity_km_s=row.relative_velocity_km_s,
        radial_km=row.radial_km,
        in_track_km=row.in_track_km,
        cross_track_km=row.cross_track_km,
        combined_radius_m=row.combined_radius_m,
        risk_score=row.risk_score,
        risk_tier=RiskTier(row.risk_tier),
        confidence=row.confidence,
        confidence_note=row.confidence_note,
        max_epoch_age_hours=row.max_epoch_age_hours,
        screened_at=_ensure_utc(row.screened_at),
    )


def catalog_object_to_row_kwargs(obj: CatalogObject) -> dict[str, Any]:
    """Column values for an ``objects`` upsert. ``epoch_age_hours`` is dropped
    on purpose -- it is not a column."""
    return {
        "norad_id": obj.norad_id,
        "name": obj.name,
        "tle_line1": obj.tle_line1,
        "tle_line2": obj.tle_line2,
        "epoch": _ensure_utc(obj.epoch),
        "object_type": obj.object_type.value,
        "rcs_size": obj.rcs_size.value,
        "radius_m": obj.radius_m,
        "perigee_km": obj.perigee_km,
        "apogee_km": obj.apogee_km,
        "inclination_deg": obj.inclination_deg,
    }


def conjunction_event_to_row_kwargs(
    event: ConjunctionEvent, *, screening_run_id: int | None
) -> dict[str, Any]:
    """Column values for a ``conjunctions`` upsert. The nested object refs
    collapse to the two foreign keys; the names are not stored."""
    return {
        "event_id": event.event_id,
        "primary_norad_id": event.primary.norad_id,
        "secondary_norad_id": event.secondary.norad_id,
        "tca": _ensure_utc(event.tca),
        "miss_distance_km": event.miss_distance_km,
        "relative_velocity_km_s": event.relative_velocity_km_s,
        "radial_km": event.radial_km,
        "in_track_km": event.in_track_km,
        "cross_track_km": event.cross_track_km,
        "combined_radius_m": event.combined_radius_m,
        "risk_score": event.risk_score,
        "risk_tier": event.risk_tier.value,
        "confidence": event.confidence,
        "confidence_note": event.confidence_note,
        "max_epoch_age_hours": event.max_epoch_age_hours,
        "screened_at": _ensure_utc(event.screened_at),
        "screening_run_id": screening_run_id,
    }
