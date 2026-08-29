"""Fully working mock DataSource, backed by contracts/fixtures.

This is the one part of the skeleton that must actually work end to end on
Day 1: `PRAHARI_DATA_SOURCE=mock make up` has to serve real-shaped data so
frontend, visualisation, and dashboard people are never blocked on the
orbital pipeline landing.

Loads fixtures once at process start and serves everything from memory —
no database required in mock mode.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from prahari_orbital.models import CatalogObject, CatalogStatus, ConjunctionEvent

from prahari_api.config import FIXTURES_DIR


@lru_cache(maxsize=1)
def _load_objects() -> list[CatalogObject]:
    raw = json.loads((FIXTURES_DIR / "objects.sample.json").read_text(encoding="utf-8"))
    return [CatalogObject.model_validate(o) for o in raw]


@lru_cache(maxsize=1)
def _load_conjunctions() -> list[ConjunctionEvent]:
    raw = json.loads((FIXTURES_DIR / "conjunctions.sample.json").read_text(encoding="utf-8"))
    return [ConjunctionEvent.model_validate(e) for e in raw]


@lru_cache(maxsize=1)
def _load_catalog_status() -> CatalogStatus:
    raw = json.loads((FIXTURES_DIR / "catalog_status.sample.json").read_text(encoding="utf-8"))
    return CatalogStatus.model_validate(raw)


class MockDataSource:
    """DataSource implementation over the frozen fixtures in contracts/fixtures/."""

    async def get_catalog_status(self) -> CatalogStatus:
        return _load_catalog_status()

    async def list_objects(
        self,
        *,
        query: str | None = None,
        object_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogObject], int]:
        objects = _load_objects()
        if query:
            q = query.lower()
            objects = [o for o in objects if q in o.name.lower()]
        if object_type:
            objects = [o for o in objects if o.object_type.value == object_type]
        total = len(objects)
        return objects[offset : offset + limit], total

    async def get_object(self, norad_id: int) -> CatalogObject | None:
        for o in _load_objects():
            if o.norad_id == norad_id:
                return o
        return None

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
        events = _load_conjunctions()
        if tier:
            events = [e for e in events if e.risk_tier.value == tier]
        if since:
            since_dt = datetime.fromisoformat(since)
            events = [e for e in events if e.tca >= since_dt]
        if until:
            until_dt = datetime.fromisoformat(until)
            events = [e for e in events if e.tca <= until_dt]
        if min_score is not None:
            events = [e for e in events if e.risk_score >= min_score]
        total = len(events)
        return events[offset : offset + limit], total

    async def get_conjunction(self, event_id: str) -> ConjunctionEvent | None:
        for e in _load_conjunctions():
            if e.event_id == event_id:
                return e
        return None

    async def get_conjunction_geometry(self, event_id: str) -> list[dict[str, float | str]]:
        event = await self.get_conjunction(event_id)
        if event is None:
            return []

        # Synthesised geometry: a straight-line approximation through the
        # known miss vector, sampled every 10s for +/-60s around TCA. This
        # is deliberately not physically propagated (mock mode has no SGP4
        # dependency) — good enough shape for the frontend to build the
        # geometry view against; services/orbital + live.py replace this
        # with real propagated samples.
        samples: list[dict[str, float | str]] = []
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

        # Synthesised circular ground track from perigee/apogee/inclination —
        # not a real SGP4 propagation. Good enough shape for OrbitView to
        # build against in mock mode; live.py replaces this with
        # frames.itrf_to_lat_lon_alt output.
        mean_alt_km = (obj.perigee_km + obj.apogee_km) / 2.0
        earth_radius_km = 6378.137
        orbital_radius_km = earth_radius_km + mean_alt_km
        period_minutes = (
            2 * math.pi * math.sqrt((orbital_radius_km * 1000) ** 3 / 3.986004418e14) / 60.0
        )

        now = datetime.now(UTC)
        samples: list[dict[str, float | str]] = []
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
