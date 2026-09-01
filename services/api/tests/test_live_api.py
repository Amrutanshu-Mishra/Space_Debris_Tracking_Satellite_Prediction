"""End-to-end tests for the Postgres-backed data source.

Run against SQLite (file-backed so the loader's engine and the request
engine share it) exercising the same repository the API uses in live mode.
Seeding goes through ``prahari_api.load.ingest`` so the loader is covered
too.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from prahari_api.config import FIXTURES_DIR, Settings
from prahari_api.data.dependency import set_data_source
from prahari_api.data.live import LiveDataSource
from prahari_api.db.cache import GeometryCache
from prahari_api.db.session import create_db_engine, create_session_maker
from prahari_api.db.tables import ConjunctionRow, ObjectRow, ScreeningRunRow
from prahari_api.load import ingest
from prahari_api.main import app

EVENTS = FIXTURES_DIR / "conjunctions.sample.json"
OBJECTS = FIXTURES_DIR / "objects.sample.json"


@pytest.fixture()
def db_url(tmp_path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'prahari.db'}"


@pytest.fixture()
def loaded(db_url: str) -> dict:
    return asyncio.run(
        ingest(events_path=EVENTS, objects_path=OBJECTS, database_url=db_url)
    )


@pytest.fixture()
def client(db_url: str, loaded: dict):
    settings = Settings(database_url=db_url, redis_url=None)
    source = LiveDataSource(settings)
    set_data_source(source)
    with TestClient(app) as test_client:
        yield test_client
    set_data_source(None)
    asyncio.run(source._engine.dispose())


def _counts(db_url: str) -> dict[str, int]:
    async def _run() -> dict[str, int]:
        engine = create_db_engine(db_url)
        maker = create_session_maker(engine)
        try:
            async with maker() as session:
                return {
                    "objects": (
                        await session.execute(select(func.count()).select_from(ObjectRow))
                    ).scalar_one(),
                    "conjunctions": (
                        await session.execute(select(func.count()).select_from(ConjunctionRow))
                    ).scalar_one(),
                    "runs": (
                        await session.execute(select(func.count()).select_from(ScreeningRunRow))
                    ).scalar_one(),
                }
        finally:
            await engine.dispose()

    return asyncio.run(_run())


# --------------------------------------------------------------- API surface


def test_live_health(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_live_catalog_status(client: TestClient) -> None:
    body = client.get("/api/v1/catalog/status").json()
    assert body["object_count"] == 200
    assert body["events_found"] == 40
    assert body["source"] == "database"
    assert "probability_of_collision" not in body
    assert "pc" not in body


def test_live_list_objects(client: TestClient) -> None:
    body = client.get("/api/v1/objects?limit=10").json()
    assert body["total"] == 200
    assert len(body["items"]) == 10

    search = client.get("/api/v1/objects?q=iss").json()
    assert search["total"] >= 1
    assert any("ISS" in o["name"] for o in search["items"])

    typed = client.get("/api/v1/objects?type=PAYLOAD").json()
    assert typed["items"]
    assert all(o["object_type"] == "PAYLOAD" for o in typed["items"])


def test_live_get_object(client: TestClient) -> None:
    resp = client.get("/api/v1/objects/25544")
    assert resp.status_code == 200
    assert resp.json()["name"] == "ISS (ZARYA)"


def test_live_get_object_404(client: TestClient) -> None:
    assert client.get("/api/v1/objects/999999").status_code == 404


def test_live_object_track(client: TestClient) -> None:
    body = client.get("/api/v1/objects/25544/track?hours=6").json()
    assert body
    assert {"lat_deg", "lon_deg", "alt_km"} <= body[0].keys()


def test_live_list_conjunctions(client: TestClient) -> None:
    body = client.get("/api/v1/conjunctions").json()
    assert body["total"] == 40
    for event in body["items"]:
        assert "probability_of_collision" not in event
        assert "pc" not in event

    red = client.get("/api/v1/conjunctions?tier=RED").json()
    assert red["total"] == 4
    assert all(e["risk_tier"] == "RED" for e in red["items"])

    scored = client.get("/api/v1/conjunctions?min_score=0.8").json()
    assert all(e["risk_score"] >= 0.8 for e in scored["items"])


def test_live_conjunction_names_joined_not_stored(client: TestClient) -> None:
    """primary/secondary names come back via the FK join, not a stored column."""
    event = client.get("/api/v1/conjunctions?limit=1").json()["items"][0]
    assert event["primary"]["name"]
    assert event["secondary"]["name"]
    assert not hasattr(ConjunctionRow, "primary_name")


def test_live_get_conjunction_and_geometry(client: TestClient) -> None:
    event_id = client.get("/api/v1/conjunctions?limit=1").json()["items"][0]["event_id"]

    resp = client.get(f"/api/v1/conjunctions/{event_id}")
    assert resp.status_code == 200
    assert resp.json()["event_id"] == event_id

    geometry = client.get(f"/api/v1/conjunctions/{event_id}/geometry").json()
    assert geometry
    assert "separation_km" in geometry[0]


def test_live_get_conjunction_404(client: TestClient) -> None:
    resp = client.get("/api/v1/conjunctions/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_live_stream_snapshot(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/stream") as ws:
        message = ws.receive_json()
        assert message["type"] == "snapshot"
        assert len(message["data"]) == 40


# ------------------------------------------------------ storage-design invariants


def test_epoch_age_hours_is_computed_not_stored(client: TestClient) -> None:
    assert not hasattr(ObjectRow, "epoch_age_hours")
    obj = client.get("/api/v1/objects/25544").json()
    # Recomputed against the wall clock: fixture epochs are well in the past,
    # so the served age exceeds the stale value baked into the fixture (29.9h
    # for the first object, all fixture epochs within a day of each other).
    assert obj["epoch_age_hours"] >= 0.0
    assert obj["epoch_age_hours"] > 100.0


def test_loader_is_idempotent(db_url: str, loaded: dict) -> None:
    before = _counts(db_url)
    again = asyncio.run(ingest(events_path=EVENTS, objects_path=OBJECTS, database_url=db_url))
    after = _counts(db_url)

    assert again["screening_run_id"] == loaded["screening_run_id"]
    assert after == before
    assert after["objects"] == 200
    assert after["conjunctions"] == 40
    assert after["runs"] == 1


def test_geometry_cache_degrades_when_redis_unreachable() -> None:
    cache = GeometryCache("redis://127.0.0.1:1/0", ttl_seconds=1)

    async def _exercise() -> None:
        assert await cache.get("any-event") is None
        await cache.set("any-event", [{"separation_km": 1.0}])  # must not raise
        await cache.close()

    asyncio.run(_exercise())
