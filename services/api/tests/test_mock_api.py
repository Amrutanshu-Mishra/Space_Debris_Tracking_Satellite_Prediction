"""End-to-end tests against the mock API. These must pass on Day 1 — the
mock data layer is the one part of the skeleton that is fully implemented.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("PRAHARI_DATA_SOURCE", "mock")
# Pin to the curated 40-event sample. conjunctions.real.json is now real
# screening output — its event count and tier mix depend on the catalogue
# snapshot and the run time, so exact-count assertions below must not run
# against it.
os.environ.setdefault(
    "PRAHARI_EVENTS_PATH",
    str(Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "conjunctions.sample.json"),
)

from fastapi.testclient import TestClient

from prahari_api.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["data_source"] == "mock"


def test_catalog_status() -> None:
    resp = client.get("/api/v1/catalog/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["object_count"] == 200
    assert "probability_of_collision" not in body


def test_list_objects() -> None:
    resp = client.get("/api/v1/objects?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 200
    assert len(body["items"]) == 10


def test_get_object_iss() -> None:
    resp = client.get("/api/v1/objects/25544")
    assert resp.status_code == 200
    assert resp.json()["name"] == "ISS (ZARYA)"


def test_get_object_404() -> None:
    resp = client.get("/api/v1/objects/999999")
    assert resp.status_code == 404


def test_object_track() -> None:
    resp = client.get("/api/v1/objects/25544/track?hours=6")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) > 0
    assert "lat_deg" in body[0]


def test_list_conjunctions() -> None:
    resp = client.get("/api/v1/conjunctions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 40
    for event in body["items"]:
        assert "probability_of_collision" not in event
        assert "pc" not in event


def test_list_conjunctions_filter_by_tier() -> None:
    resp = client.get("/api/v1/conjunctions?tier=RED")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4
    assert all(e["risk_tier"] == "RED" for e in body["items"])


def test_conjunctions_carry_intra_constellation_flag() -> None:
    body = client.get("/api/v1/conjunctions?limit=500").json()
    assert body["items"]
    assert all(isinstance(e["intra_constellation"], bool) for e in body["items"])


def test_exclude_intra_constellation_param_is_wired() -> None:
    unfiltered = client.get("/api/v1/conjunctions?limit=500").json()
    filtered = client.get(
        "/api/v1/conjunctions?limit=500&exclude_intra_constellation=true"
    ).json()
    assert filtered["total"] <= unfiltered["total"]
    assert not any(e["intra_constellation"] for e in filtered["items"])
    # the curated sample deliberately contains no same-constellation pairs
    assert filtered["total"] == unfiltered["total"]


def test_get_conjunction_and_geometry() -> None:
    listing = client.get("/api/v1/conjunctions?limit=1").json()
    event_id = listing["items"][0]["event_id"]

    resp = client.get(f"/api/v1/conjunctions/{event_id}")
    assert resp.status_code == 200
    assert resp.json()["event_id"] == event_id

    geometry = client.get(f"/api/v1/conjunctions/{event_id}/geometry")
    assert geometry.status_code == 200
    assert len(geometry.json()) > 0


def test_get_conjunction_404() -> None:
    resp = client.get("/api/v1/conjunctions/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_stream_snapshot() -> None:
    with client.websocket_connect("/api/v1/stream") as ws:
        message = ws.receive_json()
        assert message["type"] == "snapshot"
        assert len(message["data"]) == 40
