"""``DataSource`` implementation backed by the optional Postgres schema.

This is the "repository layer": the routers depend only on the
``DataSource`` protocol, so they cannot tell whether a response came from
this class or from :class:`prahari_api.data.mock.MockDataSource`. Both return
the same frozen Pydantic models.

Read model vs. storage model differences (nested object refs -> foreign
keys, computed ``epoch_age_hours``, ``CatalogStatus`` assembled from
``screening_runs`` + ``objects``) are all handled in
:mod:`prahari_api.db.session`. The geometry endpoint additionally goes
through :class:`prahari_api.db.cache.GeometryCache`.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from fastapi import HTTPException
from prahari_orbital.models import CatalogObject, CatalogStatus, ConjunctionEvent, EpochAgeDistribution
from prahari_orbital.propagate import propagate_one
from sqlalchemy import func, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from prahari_api.config import Settings
from prahari_api.db.cache import GeometryCache
from prahari_api.db.session import (
    create_db_engine,
    create_session_maker,
    init_db,
    row_to_catalog_object,
    row_to_conjunction_event,
)
from prahari_api.db.tables import ConjunctionRow, ObjectRow, ScreeningRunRow


class DbDataSource:
    """Serves the API surface from Postgres. Selected when ``DATABASE_URL``
    is set (see :func:`prahari_api.data.dependency.get_data_source`)."""

    def __init__(
        self,
        settings: Settings,
        *,
        engine: AsyncEngine | None = None,
        session_maker: async_sessionmaker[AsyncSession] | None = None,
        geometry_cache: GeometryCache | None = None,
    ) -> None:
        if engine is None and not settings.database_url:
            raise RuntimeError("DbDataSource requires DATABASE_URL or an explicit engine")
        self._settings = settings
        self._engine = engine or create_db_engine(settings.database_url or "")
        self._session_maker = session_maker or create_session_maker(self._engine)
        self._cache = geometry_cache or GeometryCache(
            settings.redis_url, ttl_seconds=settings.geometry_cache_ttl_seconds
        )
        self._initialized = False

    async def ensure_db(self) -> None:
        if not self._initialized:
            await init_db(self._engine)
            self._initialized = True

    # ------------------------------------------------------------------ status

    async def get_catalog_status(self) -> CatalogStatus:
        await self.ensure_db()
        async with self._session_maker() as session:
            run = (
                await session.execute(
                    select(ScreeningRunRow).order_by(
                        ScreeningRunRow.started_at.desc(), ScreeningRunRow.id.desc()
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if run is None:
                raise HTTPException(status_code=404, detail="No screening run recorded")

            object_count = (
                await session.execute(select(func.count()).select_from(ObjectRow))
            ).scalar_one() or 0
            epochs = list(
                (await session.execute(select(ObjectRow.epoch))).scalars().all()
            )

        now = datetime.now(UTC)
        ages = sorted(
            max(0.0, (now - (e if e.tzinfo else e.replace(tzinfo=UTC))).total_seconds() / 3600.0)
            for e in epochs
        )
        distribution = EpochAgeDistribution(
            p50=_percentile(ages, 50),
            p90=_percentile(ages, 90),
            max=ages[-1] if ages else 0.0,
        )
        started_at = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=UTC)
        return CatalogStatus(
            object_count=object_count,
            last_refresh=started_at,
            next_refresh=started_at + timedelta(hours=self._settings.screening_interval_hours),
            source="database",
            epoch_age_hours=distribution,
            screening_window_hours=run.window_hours,
            last_screen_duration_s=run.duration_s,
            pairs_considered=run.pairs_considered,
            pairs_fine_screened=run.pairs_fine_screened,
            events_found=run.events_found,
        )

    # ----------------------------------------------------------------- objects

    async def list_objects(
        self,
        *,
        query: str | None = None,
        object_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogObject], int]:
        await self.ensure_db()
        async with self._session_maker() as session:
            stmt = select(ObjectRow)
            count_stmt = select(func.count()).select_from(ObjectRow)
            if query:
                f = ObjectRow.name.ilike(f"%{query}%")
                stmt, count_stmt = stmt.where(f), count_stmt.where(f)
            if object_type:
                f = ObjectRow.object_type == object_type
                stmt, count_stmt = stmt.where(f), count_stmt.where(f)

            total = (await session.execute(count_stmt)).scalar_one() or 0
            rows = (
                await session.execute(
                    stmt.order_by(ObjectRow.norad_id.asc()).limit(limit).offset(offset)
                )
            ).scalars().all()
        now = datetime.now(UTC)
        return [row_to_catalog_object(r, now=now) for r in rows], total

    async def get_object(self, norad_id: int) -> CatalogObject | None:
        await self.ensure_db()
        async with self._session_maker() as session:
            row = (
                await session.execute(select(ObjectRow).where(ObjectRow.norad_id == norad_id))
            ).scalar_one_or_none()
        return row_to_catalog_object(row) if row is not None else None

    # ------------------------------------------------------------- conjunctions

    async def list_conjunctions(
        self,
        *,
        tier: str | None = None,
        since: str | None = None,
        until: str | None = None,
        min_score: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ConjunctionEvent], int]:
        await self.ensure_db()
        primary = aliased(ObjectRow)
        secondary = aliased(ObjectRow)
        async with self._session_maker() as session:
            stmt = (
                select(ConjunctionRow, primary.name, secondary.name)
                .join(primary, primary.norad_id == ConjunctionRow.primary_norad_id)
                .join(secondary, secondary.norad_id == ConjunctionRow.secondary_norad_id)
            )
            count_stmt = select(func.count()).select_from(ConjunctionRow)

            if tier:
                f = ConjunctionRow.risk_tier == tier
                stmt, count_stmt = stmt.where(f), count_stmt.where(f)
            if since:
                f = ConjunctionRow.tca >= datetime.fromisoformat(since)
                stmt, count_stmt = stmt.where(f), count_stmt.where(f)
            if until:
                f = ConjunctionRow.tca <= datetime.fromisoformat(until)
                stmt, count_stmt = stmt.where(f), count_stmt.where(f)
            if min_score is not None:
                f = ConjunctionRow.risk_score >= min_score
                stmt, count_stmt = stmt.where(f), count_stmt.where(f)

            total = (await session.execute(count_stmt)).scalar_one() or 0
            result = await session.execute(
                stmt.order_by(ConjunctionRow.tca.asc()).limit(limit).offset(offset)
            )
            events = [
                row_to_conjunction_event(row, primary_name=p_name, secondary_name=s_name)
                for row, p_name, s_name in result.all()
            ]
        return events, total

    async def get_conjunction(self, event_id: str) -> ConjunctionEvent | None:
        await self.ensure_db()
        primary = aliased(ObjectRow)
        secondary = aliased(ObjectRow)
        async with self._session_maker() as session:
            row = (
                await session.execute(
                    select(ConjunctionRow, primary.name, secondary.name)
                    .join(primary, primary.norad_id == ConjunctionRow.primary_norad_id)
                    .join(secondary, secondary.norad_id == ConjunctionRow.secondary_norad_id)
                    .where(ConjunctionRow.event_id == event_id)
                )
            ).first()
        if row is None:
            return None
        conj, p_name, s_name = row
        return row_to_conjunction_event(conj, primary_name=p_name, secondary_name=s_name)

    # -------------------------------------------------------------- geometry

    async def get_conjunction_geometry(self, event_id: str) -> list[dict[str, Any]]:
        cached = await self._cache.get(event_id)
        if cached is not None:
            return cached

        event = await self.get_conjunction(event_id)
        if event is None:
            return []
        primary_obj = await self.get_object(event.primary.norad_id)
        secondary_obj = await self.get_object(event.secondary.norad_id)
        if primary_obj is None or secondary_obj is None:
            return []

        samples = _propagate_geometry(event, primary_obj, secondary_obj)
        await self._cache.set(event_id, samples)
        return samples

    # ----------------------------------------------------------------- tracks

    async def get_object_track(
        self, norad_id: int, *, hours: float = 24.0
    ) -> list[dict[str, float | str]]:
        obj = await self.get_object(norad_id)
        if obj is None:
            return []

        now = datetime.now(UTC)
        step_seconds = 300
        h_int = max(1, math.ceil(hours))
        try:
            ephem = propagate_one(obj, start=now, hours=h_int, step_seconds=step_seconds)
            lats, lons, alts = ephem.subpoint()
            n = min(len(lats), int(hours * 3600 // step_seconds) + 1)
            return [
                {
                    "t": (now + timedelta(seconds=i * step_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "lat_deg": round(float(lats[i]), 4),
                    "lon_deg": round(float(lons[i]), 4),
                    "alt_km": round(float(alts[i]), 1),
                }
                for i in range(n)
            ]
        except (ValueError, RuntimeError, TypeError):
            return _circular_track_fallback(obj, hours=hours, now=now)


# --------------------------------------------------------------------- helpers


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[int(rank)]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (rank - lo)


def _propagate_geometry(
    event: ConjunctionEvent, primary_obj: CatalogObject, secondary_obj: CatalogObject
) -> list[dict[str, Any]]:
    """SGP4-propagate both objects +/- 60s around TCA at 10s steps, GCRS, km.

    Falls back to a straight-line approximation through the known miss
    vector if propagation fails (e.g. a decayed orbit)."""
    tca = event.tca if event.tca.tzinfo else event.tca.replace(tzinfo=UTC)
    start_t = tca - timedelta(seconds=60)
    try:
        ephem_pri = propagate_one(primary_obj, start=start_t, hours=1, step_seconds=10)
        ephem_sec = propagate_one(secondary_obj, start=start_t, hours=1, step_seconds=10)
        pos_pri = ephem_pri.gcrs()[:13]
        pos_sec = ephem_sec.gcrs()[:13]
        samples: list[dict[str, Any]] = []
        for i in range(13):
            p_km = pos_pri[i]
            s_km = pos_sec[i]
            samples.append(
                {
                    "t": (start_t + timedelta(seconds=i * 10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "primary_km": [round(float(c), 3) for c in p_km],
                    "secondary_km": [round(float(c), 3) for c in s_km],
                    "separation_km": round(float(np.linalg.norm(p_km - s_km)), 3),
                }
            )
        return samples
    except (ValueError, RuntimeError, TypeError):
        samples = []
        for offset_s in range(-60, 61, 10):
            frac = offset_s / 60.0
            t = tca + timedelta(seconds=offset_s)
            separation_km = event.miss_distance_km + abs(frac) * event.relative_velocity_km_s * 6.0
            samples.append(
                {
                    "t": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "separation_km": round(separation_km, 3),
                }
            )
        return samples


def _circular_track_fallback(
    obj: CatalogObject, *, hours: float, now: datetime
) -> list[dict[str, float | str]]:
    mean_alt_km = (obj.perigee_km + obj.apogee_km) / 2.0
    orbital_radius_km = 6378.137 + mean_alt_km
    period_minutes = (
        2 * math.pi * math.sqrt((orbital_radius_km * 1000) ** 3 / 3.986004418e14) / 60.0
    )
    step_minutes = 5.0
    steps = int(hours * 60 / step_minutes)
    samples: list[dict[str, float | str]] = []
    for i in range(steps + 1):
        t = now + timedelta(minutes=i * step_minutes)
        phase = 2 * math.pi * (i * step_minutes / period_minutes)
        samples.append(
            {
                "t": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "lat_deg": round(obj.inclination_deg * math.sin(phase), 4),
                "lon_deg": round(((i * step_minutes / period_minutes) * 360.0 - 180.0) % 360.0 - 180.0, 4),
                "alt_km": round(mean_alt_km, 1),
            }
        )
    return samples
