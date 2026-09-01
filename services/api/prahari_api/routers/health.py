"""GET /api/v1/health"""

from __future__ import annotations

from fastapi import APIRouter

from prahari_api.config import get_settings
from prahari_api.events import get_events

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str | int]:
    settings = get_settings()
    return {
        "status": "ok",
        "data_source": "live" if settings.use_database else "mock",
        "events_loaded": len(get_events()),
    }
