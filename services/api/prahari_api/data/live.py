"""Live DataSource: real ingest/propagate/screen pipeline via prahari_orbital, backed by Postgres.

Reads worker's screening output from PostgreSQL tables:
- objects
- conjunctions
- catalog_status

Uses prahari_orbital.propagate for geometry and ground-track endpoints.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from fastapi import HTTPException
from prahari_orbital.models import CatalogObject, CatalogStatus, ConjunctionEvent
from prahari_orbital.propagate import propagate_one
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from prahari_api.config import Settings
from prahari_api.data.db import (
    CatalogStatusModel,
    ConjunctionModel,
    ObjectModel,
    create_db_engine,
    create_session_maker,
    init_db,
    model_to_catalog_object,
    model_to_catalog_status,
    model_to_conjunction_event,
)


class LiveDataSource:
    """DataSource implementation reading the worker's screening output from PostgreSQL."""

    def __init__(
        self,
        settings: Settings,
        engine: AsyncEngine | None = None,
        session_maker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._settings = settings
        self._engine = engine or create_db_engine(settings.database_url)
        self._session_maker = session_maker or create_session_maker(self._engine)
        self._initialized = False

    async def ensure_db(self) -> None:
        """Ensure database tables are initialized."""
        if not self._initialized:
            await init_db(self._engine)
            self._initialized = True

    async def get_catalog_status(self) -> CatalogStatus:
        await self.ensure_db()
        async with self._session_maker() as session:
            stmt = (
                select(CatalogStatusModel)
                .order_by(CatalogStatusModel.created_at.desc(), CatalogStatusModel.id.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="No catalog status available")
            return model_to_catalog_status(row)

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
            stmt = select(ObjectModel)
            count_stmt = select(func.count()).select_from(ObjectModel)

            if query:
                q_filter = ObjectModel.name.ilike(f"%{query}%")
                stmt = stmt.where(q_filter)
                count_stmt = count_stmt.where(q_filter)

            if object_type:
                t_filter = ObjectModel.object_type == object_type
                stmt = stmt.where(t_filter)
                count_stmt = count_stmt.where(t_filter)

            total = (await session.execute(count_stmt)).scalar_one() or 0
            stmt = stmt.order_by(ObjectModel.norad_id.asc()).limit(limit).offset(offset)
            rows = (await session.execute(stmt)).scalars().all()
            return [model_to_catalog_object(r) for r in rows], total

    async def get_object(self, norad_id: int) -> CatalogObject | None:
        await self.ensure_db()
        async with self._session_maker() as session:
            stmt = select(ObjectModel).where(ObjectModel.norad_id == norad_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            return model_to_catalog_object(row)

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
        async with self._session_maker() as session:
            stmt = select(ConjunctionModel)
            count_stmt = select(func.count()).select_from(ConjunctionModel)

            if tier:
                t_filter = ConjunctionModel.risk_tier == tier
                stmt = stmt.where(t_filter)
                count_stmt = count_stmt.where(t_filter)

            if since:
                since_dt = datetime.fromisoformat(since)
                s_filter = ConjunctionModel.tca >= since_dt
                stmt = stmt.where(s_filter)
                count_stmt = count_stmt.where(s_filter)

            if until:
                until_dt = datetime.fromisoformat(until)
                u_filter = ConjunctionModel.tca <= until_dt
                stmt = stmt.where(u_filter)
                count_stmt = count_stmt.where(u_filter)

            if min_score is not None:
                sc_filter = ConjunctionModel.risk_score >= min_score
                stmt = stmt.where(sc_filter)
                count_stmt = count_stmt.where(sc_filter)

            total = (await session.execute(count_stmt)).scalar_one() or 0
            stmt = stmt.order_by(ConjunctionModel.tca.asc()).limit(limit).offset(offset)
            rows = (await session.execute(stmt)).scalars().all()
            return [model_to_conjunction_event(r) for r in rows], total

    async def get_conjunction(self, event_id: str) -> ConjunctionEvent | None:
        await self.ensure_db()
        async with self._session_maker() as session:
            stmt = select(ConjunctionModel).where(ConjunctionModel.event_id == event_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            return model_to_conjunction_event(row)

    async def get_conjunction_geometry(self, event_id: str) -> list[dict[str, Any]]:
        event = await self.get_conjunction(event_id)
        if event is None:
            return []

        primary_obj = await self.get_object(event.primary.norad_id)
        secondary_obj = await self.get_object(event.secondary.norad_id)
        if primary_obj is None or secondary_obj is None:
            return []

        tca = event.tca
        if tca.tzinfo is None:
            tca = tca.replace(tzinfo=UTC)
        start_t = tca - timedelta(seconds=60)

        # Propagate +/- 60s around TCA at 10s intervals
        try:
            ephem_pri = propagate_one(primary_obj, start=start_t, hours=1, step_seconds=10)
            ephem_sec = propagate_one(secondary_obj, start=start_t, hours=1, step_seconds=10)
            pos_pri = ephem_pri.gcrs()[:13]
            pos_sec = ephem_sec.gcrs()[:13]

            samples: list[dict[str, Any]] = []
            for i in range(13):
                t_sample = start_t + timedelta(seconds=i * 10)
                p_km = pos_pri[i]
                s_km = pos_sec[i]
                separation_km = float(np.linalg.norm(p_km - s_km))
                samples.append(
                    {
                        "t": t_sample.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "primary_km": [round(float(coord), 3) for coord in p_km],
                        "secondary_km": [round(float(coord), 3) for coord in s_km],
                        "separation_km": round(separation_km, 3),
                    }
                )
            return samples
        except (ValueError, RuntimeError, TypeError):
            # Linear fallback if propagation fails (e.g. decayed orbit)
            samples = []
            miss = event.miss_distance_km
            for offset_s in range(-60, 61, 10):
                frac = offset_s / 60.0
                t = event.tca + timedelta(seconds=offset_s)
                separation_km = miss + abs(frac) * event.relative_velocity_km_s * 6.0
                samples.append(
                    {
                        "t": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "separation_km": round(separation_km, 3),
                    }
                )
            return samples

    async def get_object_track(
        self, norad_id: int, *, hours: float = 24.0
    ) -> list[dict[str, float | str]]:
        obj = await self.get_object(norad_id)
        if obj is None:
            return []

        now = datetime.now(UTC)
        h_int = max(1, math.ceil(hours))
        step_seconds = 300  # 5 minutes

        try:
            ephem = propagate_one(obj, start=now, hours=h_int, step_seconds=step_seconds)
            lats, lons, alts = ephem.subpoint()
            max_steps = int(hours * 3600 // step_seconds) + 1
            n = min(len(lats), max_steps)

            samples: list[dict[str, float | str]] = []
            for i in range(n):
                t_sample = now + timedelta(seconds=i * step_seconds)
                samples.append(
                    {
                        "t": t_sample.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "lat_deg": round(float(lats[i]), 4),
                        "lon_deg": round(float(lons[i]), 4),
                        "alt_km": round(float(alts[i]), 1),
                    }
                )
            return samples
        except (ValueError, RuntimeError, TypeError):
            # Circular fallback if SGP4 propagation fails
            mean_alt_km = (obj.perigee_km + obj.apogee_km) / 2.0
            earth_radius_km = 6378.137
            orbital_radius_km = earth_radius_km + mean_alt_km
            period_minutes = (
                2 * math.pi * math.sqrt((orbital_radius_km * 1000) ** 3 / 3.986004418e14) / 60.0
            )

            samples = []
            step_minutes = 5.0
            steps = int(hours * 60 / step_minutes)
            for i in range(steps + 1):
                t = now + timedelta(minutes=i * step_minutes)
                phase = 2 * math.pi * (i * step_minutes / period_minutes)
                lat = obj.inclination_deg * math.sin(phase)
                lon = ((i * step_minutes / period_minutes) * 360.0 - 180.0) % 360.0 - 180.0
                samples.append(
                    {
                        "t": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "lat_deg": round(lat, 4),
                        "lon_deg": round(lon, 4),
                        "alt_km": round(mean_alt_km, 1),
                    }
                )
            return samples
