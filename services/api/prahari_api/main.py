"""FastAPI app entrypoint. `uvicorn prahari_api.main:app`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prahari_api.config import get_settings
from prahari_api.events import get_events
from prahari_api.routers import catalog, conjunctions, health, objects, stream

logger = logging.getLogger("prahari_api")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load and schema-validate the events file before serving a single request.

    A missing file or any violation of
    ``contracts/schemas/conjunction.schema.json`` raises here, which aborts
    startup — the API never comes up serving data that fails the contract.

    Also logs, at INFO, which mode each subsystem resolved to (see
    ``Settings.startup_summary``), so the running configuration is visible in
    the logs without any environment inspection.
    """
    # uvicorn configures the "uvicorn" logger tree but not application
    # loggers; make sure ours reaches the same stream at INFO.
    if not logging.getLogger().handlers and not logger.handlers:
        logging.basicConfig(level=logging.INFO)
    logger.setLevel(logging.INFO)

    for line in settings.startup_summary():
        logger.info("startup | %s", line)

    app.state.events_loaded = len(get_events())
    yield


app = FastAPI(
    title="PRAHARI API",
    description="Space situational awareness: catalogue, conjunctions, streaming alerts.",
    version="0.1.0",
    lifespan=lifespan,
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
