"""Tests for Celery worker tasks: refresh_catalog and run_screening."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from prahari_orbital.models import CatalogObject
from sqlalchemy import select

import prahari_worker.tasks as worker_tasks
from prahari_worker.db import (
    CatalogStatusModel,
    ConjunctionModel,
    ObjectModel,
    create_db_engine,
    create_session_maker,
    init_db,
)
from prahari_worker.tasks import refresh_catalog, run_screening

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def test_mock_mode_skips_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_tasks, "DATA_SOURCE", "mock")

    refresh_res = refresh_catalog()
    assert refresh_res["status"] == "skipped"
    assert "mock" in refresh_res["reason"]

    screening_res = run_screening()
    assert screening_res["status"] == "skipped"
    assert "mock" in screening_res["reason"]


def test_live_refresh_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_tasks, "DATA_SOURCE", "live")
    db_file = tmp_path / "test_worker.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # Run refresh_catalog in offline mode against cached catalogue
    res = refresh_catalog(database_url=db_url, group="active", offline=True, trigger_screening=False)
    assert res["status"] == "ok"
    assert res["object_count"] > 0

    # Verify rows in database
    async def _verify() -> int:
        engine = create_db_engine(db_url)
        session_maker = create_session_maker(engine)
        async with session_maker() as session:
            stmt = select(ObjectModel)
            rows = (await session.execute(stmt)).scalars().all()
            count = len(rows)
        await engine.dispose()
        return count

    count = asyncio.run(_verify())
    assert count == res["object_count"]


def test_live_run_screening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_tasks, "DATA_SOURCE", "live")
    db_file = tmp_path / "test_screening.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    raw_objects = json.loads((FIXTURES_DIR / "objects.sample.json").read_text(encoding="utf-8"))
    sample_objects = [CatalogObject.model_validate(o) for o in raw_objects[:10]]

    # Run screening on small sample of objects
    res = run_screening(
        database_url=db_url,
        hours=1.0,
        coarse_step_seconds=120,
        objects_override=sample_objects,
    )
    assert res["status"] == "ok"
    assert "events_found" in res
    assert "duration_s" in res

    # Verify catalog_status was written to DB
    async def _verify() -> bool:
        engine = create_db_engine(db_url)
        session_maker = create_session_maker(engine)
        async with session_maker() as session:
            stmt = select(CatalogStatusModel)
            status_row = (await session.execute(stmt)).scalar_one_or_none()
            has_status = status_row is not None and status_row.object_count == 10
        await engine.dispose()
        return has_status

    assert asyncio.run(_verify()) is True

