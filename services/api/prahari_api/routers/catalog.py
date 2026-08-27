"""GET /api/v1/catalog/status"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from prahari_orbital.models import CatalogStatus

from prahari_api.data import DataSource, get_data_source

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/status", response_model=CatalogStatus)
async def catalog_status(data: DataSource = Depends(get_data_source)) -> CatalogStatus:
    return await data.get_catalog_status()
