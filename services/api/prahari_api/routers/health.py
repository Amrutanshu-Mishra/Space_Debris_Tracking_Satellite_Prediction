"""GET /api/v1/health"""

from __future__ import annotations

from fastapi import APIRouter

from prahari_api.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "data_source": settings.prahari_data_source}
