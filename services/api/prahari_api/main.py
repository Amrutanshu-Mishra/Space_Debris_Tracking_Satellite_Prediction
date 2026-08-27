"""FastAPI app entrypoint. `uvicorn prahari_api.main:app`."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prahari_api.config import get_settings
from prahari_api.routers import catalog, conjunctions, health, objects, stream

settings = get_settings()

app = FastAPI(
    title="PRAHARI API",
    description="Space situational awareness: catalogue, conjunctions, streaming alerts.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(catalog.router, prefix=API_PREFIX)
app.include_router(objects.router, prefix=API_PREFIX)
app.include_router(conjunctions.router, prefix=API_PREFIX)
app.include_router(stream.router, prefix=API_PREFIX)
