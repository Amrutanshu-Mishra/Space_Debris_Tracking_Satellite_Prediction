"""GET /api/v1/objects, GET /api/v1/objects/{norad_id}, GET /api/v1/objects/{norad_id}/track"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from prahari_orbital.models import CatalogObject

from prahari_api.data import DataSource, get_data_source
from prahari_api.schemas import Page

router = APIRouter(prefix="/objects", tags=["objects"])


@router.get("", response_model=Page[CatalogObject])
async def list_objects(
    q: str | None = Query(default=None, description="Case-insensitive substring match on name"),
    type: str | None = Query(default=None, description="PAYLOAD | ROCKET_BODY | DEBRIS | UNKNOWN"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    data: DataSource = Depends(get_data_source),
) -> Page[CatalogObject]:
    items, total = await data.list_objects(query=q, object_type=type, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{norad_id}", response_model=CatalogObject)
async def get_object(norad_id: int, data: DataSource = Depends(get_data_source)) -> CatalogObject:
    obj = await data.get_object(norad_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"No object with norad_id={norad_id}")
    return obj


@router.get("/{norad_id}/track")
async def get_object_track(
    norad_id: int,
    hours: float = Query(default=24.0, gt=0, le=168),
    data: DataSource = Depends(get_data_source),
) -> list[dict[str, float | str]]:
    obj = await data.get_object(norad_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"No object with norad_id={norad_id}")
    return await data.get_object_track(norad_id, hours=hours)
