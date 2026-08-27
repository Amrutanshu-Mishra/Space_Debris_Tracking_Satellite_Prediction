"""Celery tasks: refresh_catalog, run_screening.

Both are thin orchestration over prahari_orbital — no domain logic here.
Guarded by PRAHARI_DATA_SOURCE so mock mode (the Day 1-3 default) never
runs them.
"""

from __future__ import annotations

import os

from prahari_worker.celery_app import app

DATA_SOURCE = os.environ.get("PRAHARI_DATA_SOURCE", "mock")


@app.task(name="prahari_worker.tasks.refresh_catalog")
def refresh_catalog() -> dict[str, int | str]:
    """Fetch CelesTrak, validate, and replace the objects table.

    On success, enqueues run_screening. No-op in mock mode.

    Returns:
        {"status": "skipped", "reason": "mock mode"} in mock mode, else
        {"status": "ok", "object_count": int} on success.
    """
    if DATA_SOURCE == "mock":
        return {"status": "skipped", "reason": "PRAHARI_DATA_SOURCE=mock"}
    raise NotImplementedError(
        "TODO(backend-data + orbital-core): "
        "prahari_orbital.ingest.fetch_gp_data -> parse_tle_block -> validate_tle_pair -> "
        "build_catalog_objects -> upsert into Postgres objects table -> enqueue run_screening.delay()"
    )


@app.task(name="prahari_worker.tasks.run_screening")
def run_screening() -> dict[str, int | str]:
    """Run the full coarse-filter -> fine-screen -> score pipeline and persist results.

    Writes ConjunctionEvent rows and a fresh CatalogStatus row, then
    publishes each new/changed event to the Redis pub/sub channel the API's
    /stream websocket forwards to connected clients. No-op in mock mode.

    Returns:
        {"status": "skipped", "reason": "mock mode"} in mock mode, else
        {"status": "ok", "events_found": int, "duration_s": float}.
    """
    if DATA_SOURCE == "mock":
        return {"status": "skipped", "reason": "PRAHARI_DATA_SOURCE=mock"}
    raise NotImplementedError(
        "TODO(screening-scoring + backend-data): "
        "propagate.propagate_many (coarse grid) -> filters.coarse_filter -> "
        "propagate.propagate_many (per-candidate fine grid) -> screen.screen_candidates -> "
        "scoring.build_event per result -> bulk insert conjunctions -> redis publish per event"
    )
