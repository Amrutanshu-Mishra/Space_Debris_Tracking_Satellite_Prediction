"""Celery tasks: refresh_catalog, run_screening.

Orchestrates prahari_orbital pipeline:
1. refresh_catalog: fetches CelesTrak active catalog, validates, updates objects table in PostgreSQL,
   and enqueues run_screening.
2. run_screening: loads catalog from PostgreSQL, propagates, applies coarse filter,
   fine screens, scores events, persists ConjunctionEvents and CatalogStatus telemetry,
   and publishes events to Redis pub/sub.

Guarded by PRAHARI_DATA_SOURCE so mock mode never runs them.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import redis
from prahari_orbital.filters import CandidatePair, apogee_perigee_filter
from prahari_orbital.ingest import _percentile, fetch_catalog
from prahari_orbital.models import CatalogObject, CatalogStatus, ConjunctionEvent, EpochAgeDistribution
from prahari_orbital.propagate import propagate_catalog
from prahari_orbital.scoring import score
from prahari_orbital.screen import screen_candidates
from sqlalchemy import select

from prahari_worker.celery_app import app
from prahari_worker.db import (
    CatalogStatusModel,
    ConjunctionModel,
    ObjectModel,
    catalog_object_to_dict,
    catalog_status_to_dict,
    conjunction_event_to_dict,
    create_db_engine,
    create_session_maker,
    init_db,
    model_to_catalog_object,
)

DATA_SOURCE = os.environ.get("PRAHARI_DATA_SOURCE", "mock")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://prahari:prahari@localhost:5432/prahari")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CONJUNCTION_STREAM_CHANNEL = os.environ.get("CONJUNCTION_STREAM_CHANNEL", "prahari:conjunction_events")
SCREENING_WINDOW_HOURS = float(os.environ.get("SCREENING_WINDOW_HOURS", "72"))
SCREENING_INTERVAL_HOURS = float(os.environ.get("SCREENING_INTERVAL_HOURS", "6"))
COARSE_FILTER_THRESHOLD_KM = float(os.environ.get("COARSE_FILTER_THRESHOLD_KM", "25.0"))


ORBITAL_CACHE_DIR = Path(__file__).resolve().parents[2] / "orbital" / "data" / "cache"
if not ORBITAL_CACHE_DIR.exists():
    ORBITAL_CACHE_DIR = Path("data/cache")


async def _async_refresh_catalog(
    database_url: str = DATABASE_URL,
    group: str = "active",
    offline: bool = False,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Fetch CelesTrak, validate, and update the objects table in PostgreSQL."""
    resolved_cache = cache_dir or ORBITAL_CACHE_DIR
    snapshot = fetch_catalog(group=group, offline=offline, cache_dir=resolved_cache)
    objects = snapshot.objects

    engine = create_db_engine(database_url)
    await init_db(engine)
    session_maker = create_session_maker(engine)

    async with session_maker() as session:
        for obj in objects:
            await session.merge(ObjectModel(**catalog_object_to_dict(obj)))
        await session.commit()

    await engine.dispose()
    return {"status": "ok", "object_count": len(objects)}


@app.task(name="prahari_worker.tasks.refresh_catalog")
def refresh_catalog(
    database_url: str = DATABASE_URL,
    group: str = "active",
    offline: bool = False,
    trigger_screening: bool = True,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Fetch CelesTrak, validate, and replace/update the objects table.

    On success, enqueues run_screening. No-op in mock mode.
    """
    if DATA_SOURCE == "mock":
        return {"status": "skipped", "reason": "PRAHARI_DATA_SOURCE=mock"}

    result = asyncio.run(
        _async_refresh_catalog(
            database_url=database_url, group=group, offline=offline, cache_dir=cache_dir
        )
    )

    if trigger_screening:
        try:
            run_screening.delay()
        except Exception:
            # If broker is unavailable (e.g. running in test without Celery worker), do not fail task
            pass

    return result


async def _async_run_screening(
    database_url: str = DATABASE_URL,
    redis_url: str = REDIS_URL,
    channel: str = CONJUNCTION_STREAM_CHANNEL,
    hours: float = SCREENING_WINDOW_HOURS,
    coarse_step_seconds: int = 60,
    threshold_km: float = COARSE_FILTER_THRESHOLD_KM,
    objects_override: list[CatalogObject] | None = None,
) -> dict[str, Any]:
    """Run the coarse-filter -> fine-screen -> score pipeline and persist results."""
    t0 = time.perf_counter()
    engine = create_db_engine(database_url)
    await init_db(engine)
    session_maker = create_session_maker(engine)

    if objects_override is not None:
        objects = objects_override
    else:
        async with session_maker() as session:
            stmt = select(ObjectModel).order_by(ObjectModel.norad_id.asc())
            rows = (await session.execute(stmt)).scalars().all()
            objects = [model_to_catalog_object(r) for r in rows]

    if len(objects) < 2:
        await engine.dispose()
        return {"status": "skipped", "reason": "fewer than 2 objects in catalogue", "events_found": 0}

    # Deduplicate objects by NORAD ID
    by_id: dict[int, CatalogObject] = {}
    for o in objects:
        by_id.setdefault(o.norad_id, o)
    catalogue = list(by_id.values())

    window_start = datetime.now(UTC)
    int_hours = max(1, int(math_hours := hours))

    # 1. Batch propagate catalogue to identify usable orbits
    ephemeris = propagate_catalog(catalogue, window_start, int_hours, coarse_step_seconds)
    usable_ids = {int(nid) for nid in ephemeris.norad_ids}
    usable = [obj for obj in catalogue if obj.norad_id in usable_ids]
    objects_by_id = {obj.norad_id: obj for obj in usable}

    if len(usable) < 2:
        await engine.dispose()
        return {"status": "skipped", "reason": "fewer than 2 usable objects after propagation", "events_found": 0}

    # 2. Analytic apogee/perigee filter
    filtered = apogee_perigee_filter(usable)
    candidates = [
        CandidatePair(
            primary_norad_id=low_id,
            secondary_norad_id=high_id,
            min_separation_km=float("inf"),
        )
        for low_id, high_id in filtered.pairs
    ]

    # 3. Fine screening
    results = screen_candidates(
        objects_by_id,
        candidates,
        start=window_start,
        window_hours=float(hours),
        coarse_step_seconds=float(coarse_step_seconds),
        threshold_km=threshold_km,
    )

    # 4. Score close approaches
    screened_at = datetime.now(UTC)
    events: list[ConjunctionEvent] = [
        score(
            res,
            objects_by_id[res.primary_norad_id],
            objects_by_id[res.secondary_norad_id],
            screened_at=screened_at,
        )
        for res in results
    ]

    # 5. Persist ConjunctionEvents
    async with session_maker() as session:
        for event in events:
            await session.merge(ConjunctionModel(**conjunction_event_to_dict(event)))

        # Telemetry calculations
        ages = sorted(o.epoch_age_hours for o in catalogue)
        p50 = _percentile(ages, 50.0) if ages else 0.0
        p90 = _percentile(ages, 90.0) if ages else 0.0
        max_age = ages[-1] if ages else 0.0

        duration_s = time.perf_counter() - t0
        status = CatalogStatus(
            object_count=len(catalogue),
            last_refresh=window_start,
            next_refresh=window_start + timedelta(hours=SCREENING_INTERVAL_HOURS),
            source="celestrak-gp-active",
            epoch_age_hours=EpochAgeDistribution(p50=round(p50, 1), p90=round(p90, 1), max=round(max_age, 1)),
            screening_window_hours=float(hours),
            last_screen_duration_s=round(duration_s, 2),
            pairs_considered=filtered.total_pairs,
            pairs_fine_screened=len(candidates),
            events_found=len(events),
        )
        session.add(CatalogStatusModel(**catalog_status_to_dict(status)))
        await session.commit()

    await engine.dispose()

    # 6. Publish each ConjunctionEvent to Redis pub/sub
    try:
        r = redis.Redis.from_url(redis_url)
        for event in events:
            r.publish(channel, event.model_dump_json())
        r.close()
    except Exception:
        # If Redis is unavailable (e.g. unit tests without Redis daemon), do not fail task
        pass

    return {"status": "ok", "events_found": len(events), "duration_s": round(duration_s, 2)}


@app.task(name="prahari_worker.tasks.run_screening")
def run_screening(
    database_url: str = DATABASE_URL,
    redis_url: str = REDIS_URL,
    channel: str = CONJUNCTION_STREAM_CHANNEL,
    hours: float = SCREENING_WINDOW_HOURS,
    coarse_step_seconds: int = 60,
    threshold_km: float = COARSE_FILTER_THRESHOLD_KM,
    objects_override: list[CatalogObject] | None = None,
) -> dict[str, Any]:
    """Run the full coarse-filter -> fine-screen -> score pipeline and persist results.

    Writes ConjunctionEvent rows and a fresh CatalogStatus row, then
    publishes each event to the Redis pub/sub channel. No-op in mock mode.
    """
    if DATA_SOURCE == "mock":
        return {"status": "skipped", "reason": "PRAHARI_DATA_SOURCE=mock"}

    return asyncio.run(
        _async_run_screening(
            database_url=database_url,
            redis_url=redis_url,
            channel=channel,
            hours=hours,
            coarse_step_seconds=coarse_step_seconds,
            threshold_km=threshold_km,
            objects_override=objects_override,
        )
    )
