"""End-to-end tests for LiveDataSource and API endpoints backed by a real database."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from prahari_orbital.models import CatalogObject, CatalogStatus, ConjunctionEvent

from prahari_api.config import FIXTURES_DIR, Settings
from prahari_api.data.db import (
    CatalogStatusModel,
    ConjunctionModel,
    ObjectModel,
    catalog_object_to_dict,
    catalog_status_to_dict,
    conjunction_event_to_dict,
    create_db_engine,
    create_session_maker,
    init_db,
)
from prahari_api.data.dependency import set_data_source
from prahari_api.data.live import LiveDataSource
from prahari_api.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def setup_live_api():
    import asyncio

    engine = create_db_engine(TEST_DB_URL)
    session_maker = create_session_maker(engine)

    async def _setup() -> None:
        await init_db(engine)
        raw_objects = json.loads((FIXTURES_DIR / "objects.sample.json").read_text(encoding="utf-8"))
        objects = [CatalogObject.model_validate(o) for o in raw_objects]

        raw_conjunctions = json.loads((FIXTURES_DIR / "conjunctions.sample.json").read_text(encoding="utf-8"))
        conjunctions = [ConjunctionEvent.model_validate(e) for e in raw_conjunctions]

        raw_status = json.loads((FIXTURES_DIR / "catalog_status.sample.json").read_text(encoding="utf-8"))
        status = CatalogStatus.model_validate(raw_status)

        async with session_maker() as session:
            for obj in objects:
                session.add(ObjectModel(**catalog_object_to_dict(obj)))
            for conj in conjunctions:
                session.add(ConjunctionModel(**conjunction_event_to_dict(conj)))
            session.add(CatalogStatusModel(**catalog_status_to_dict(status)))
            await session.commit()

    asyncio.run(_setup())

    settings = Settings(
        prahari_data_source="live",
        database_url=TEST_DB_URL,
    )
    live_source = LiveDataSource(settings=settings, engine=engine, session_maker=session_maker)
    set_data_source(live_source)

    yield

    set_data_source(None)
    asyncio.run(engine.dispose())


client = TestClient(app)


def test_live_health() -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_live_catalog_status() -> None:
    resp = client.get("/api/v1/catalog/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["object_count"] == 200
    assert "probability_of_collision" not in body
    assert "pc" not in body


def test_live_list_objects() -> None:
    resp = client.get("/api/v1/objects?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 200
    assert len(body["items"]) == 10

    # Test case-insensitive search
    search_resp = client.get("/api/v1/objects?q=iss")
    assert search_resp.status_code == 200
    search_body = search_resp.json()
    assert search_body["total"] >= 1
    assert any("ISS" in o["name"] for o in search_body["items"])

    # Test object type filter
    type_resp = client.get("/api/v1/objects?type=PAYLOAD")
    assert type_resp.status_code == 200
    type_body = type_resp.json()
    assert all(o["object_type"] == "PAYLOAD" for o in type_body["items"])


def test_live_get_object() -> None:
    resp = client.get("/api/v1/objects/25544")
    assert resp.status_code == 200
    assert resp.json()["name"] == "ISS (ZARYA)"


def test_live_get_object_404() -> None:
    resp = client.get("/api/v1/objects/999999")
    assert resp.status_code == 404


def test_live_object_track() -> None:
    resp = client.get("/api/v1/objects/25544/track?hours=6")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) > 0
    assert "lat_deg" in body[0]
    assert "lon_deg" in body[0]
    assert "alt_km" in body[0]


def test_live_list_conjunctions() -> None:
    resp = client.get("/api/v1/conjunctions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 40
    for event in body["items"]:
        assert "probability_of_collision" not in event
        assert "pc" not in event

    # Filter by risk tier
    tier_resp = client.get("/api/v1/conjunctions?tier=RED")
    assert tier_resp.status_code == 200
    tier_body = tier_resp.json()
    assert tier_body["total"] == 4
    assert all(e["risk_tier"] == "RED" for e in tier_body["items"])

    # Filter by min_score
    score_resp = client.get("/api/v1/conjunctions?min_score=0.8")
    assert score_resp.status_code == 200
    assert all(e["risk_score"] >= 0.8 for e in score_resp.json()["items"])


def test_live_get_conjunction_and_geometry() -> None:
    listing = client.get("/api/v1/conjunctions?limit=1").json()
    event_id = listing["items"][0]["event_id"]

    resp = client.get(f"/api/v1/conjunctions/{event_id}")
    assert resp.status_code == 200
    assert resp.json()["event_id"] == event_id

    geometry = client.get(f"/api/v1/conjunctions/{event_id}/geometry")
    assert geometry.status_code == 200
    geom_body = geometry.json()
    assert len(geom_body) > 0
    assert "separation_km" in geom_body[0]


def test_live_get_conjunction_404() -> None:
    resp = client.get("/api/v1/conjunctions/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_live_stream_snapshot() -> None:
    with client.websocket_connect("/api/v1/stream") as ws:
        message = ws.receive_json()
        assert message["type"] == "snapshot"
        assert len(message["data"]) == 40

