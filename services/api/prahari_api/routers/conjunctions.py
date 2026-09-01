"""GET /api/v1/conjunctions, GET /api/v1/conjunctions/{event_id}, .../geometry"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from prahari_orbital.models import ConjunctionEvent

from prahari_api.data import DataSource, get_data_source
from prahari_api.schemas import Page

router = APIRouter(prefix="/conjunctions", tags=["conjunctions"])


@router.get("", response_model=Page[ConjunctionEvent])
async def list_conjunctions(
    tier: str | None = Query(default=None, description="GREEN | AMBER | RED"),
    since: str | None = Query(default=None, description="ISO 8601 UTC, inclusive lower bound on tca"),
    until: str | None = Query(default=None, description="ISO 8601 UTC, inclusive upper bound on tca"),
    min_score: float | None = Query(default=None, ge=0, le=1),
    exclude_intra_constellation: bool = Query(
        default=False,
        description="Drop pairs where both objects are the same station-kept "
        "constellation (Starlink/OneWeb/Globalstar/Iridium). The list view "
        "sets this true by default.",
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    data: DataSource = Depends(get_data_source),
) -> Page[ConjunctionEvent]:
    items, total = await data.list_conjunctions(
        tier=tier,
        since=since,
        until=until,
        min_score=min_score,
        exclude_intra_constellation=exclude_intra_constellation,
        limit=limit,
        offset=offset,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{event_id}", response_model=ConjunctionEvent)
async def get_conjunction(event_id: str, data: DataSource = Depends(get_data_source)) -> ConjunctionEvent:
    event = await data.get_conjunction(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"No conjunction event with event_id={event_id}")
    return event


@router.get("/{event_id}/geometry")
async def get_conjunction_geometry(
    event_id: str, data: DataSource = Depends(get_data_source)
) -> list[dict[str, Any]]:
    event = await data.get_conjunction(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"No conjunction event with event_id={event_id}")
    return await data.get_conjunction_geometry(event_id)
