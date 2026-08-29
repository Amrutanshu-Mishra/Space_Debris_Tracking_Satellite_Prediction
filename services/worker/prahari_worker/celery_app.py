"""Celery app + Beat schedule.

Two periodic tasks:
    refresh_catalog    every SCREENING_INTERVAL_HOURS (6h default) — re-fetch
                        CelesTrak, rebuild the object table.
    run_screening       runs immediately after refresh_catalog completes —
                        coarse filter -> fine screen -> score -> write
                        conjunction events + publish to Redis pub/sub for
                        the API's /stream websocket to forward.

PRAHARI_DATA_SOURCE=mock disables both tasks entirely (see tasks.py) so
running `make up` in mock mode never touches the network or spends CPU on
a pipeline nobody's using yet.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
SCREENING_INTERVAL_HOURS = float(os.environ.get("SCREENING_INTERVAL_HOURS", "6"))

app = Celery(
    "prahari_worker", broker=REDIS_URL, backend=RESULT_BACKEND, include=["prahari_worker.tasks"]
)

app.conf.beat_schedule = {
    "refresh-catalog": {
        "task": "prahari_worker.tasks.refresh_catalog",
        "schedule": crontab(minute=0, hour=f"*/{int(SCREENING_INTERVAL_HOURS)}"),
    },
}
app.conf.timezone = "UTC"
