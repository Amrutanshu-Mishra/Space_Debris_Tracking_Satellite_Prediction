"""Integration: raw TLE text -> ingest -> CatalogObject -> propagate_one.

Every other test drives ingest and propagate in isolation. That let an
attribute-name mismatch through: propagate's satellite builder read ``.line1``
/ ``.line2`` (fields that exist only on the ingest-internal ``TLERecord``),
while the frozen-contract ``CatalogObject`` that the ingest path actually
produces names them ``tle_line1`` / ``tle_line2``. This test exercises the two
modules together so that seam stays covered.

Reference element set: the published SGP4 verification TLE for the ISS
(NORAD 25544, epoch 2008-264) from Vallado et al., "Revisiting Spacetrack
Report #3" — the same lines used in test_ingest.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

from prahari_orbital.ingest import build_catalog_objects, parse_tle_block
from prahari_orbital.models import CatalogObject
from prahari_orbital.propagate import Ephemeris, propagate_one

ISS_NAME = "ISS (ZARYA)"
ISS_LINE1 = "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927"
ISS_LINE2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"
RAW_TLE = "\r\n".join([ISS_NAME, ISS_LINE1, ISS_LINE2]) + "\r\n"


def _iss_catalog_object() -> CatalogObject:
    """Run the real ingest path: raw text -> parse_tle_block -> build_catalog_objects."""
    triples = parse_tle_block(RAW_TLE)
    objects = build_catalog_objects(triples, now_utc="2008-09-20T12:25:00Z")
    assert len(objects) == 1
    return objects[0]


def test_ingested_catalog_object_feeds_propagate_one() -> None:
    obj = _iss_catalog_object()
    # Sanity: the ingest path really produced the contract field names.
    assert obj.tle_line1 == ISS_LINE1
    assert obj.tle_line2 == ISS_LINE2

    start = datetime(2008, 9, 20, 12, 25, tzinfo=timezone.utc)
    hours, step_seconds = 3, 60
    eph = propagate_one(obj, start, hours=hours, step_seconds=step_seconds)

    n_steps = hours * 3600 // step_seconds + 1  # inclusive of both ends

    assert isinstance(eph, Ephemeris)
    assert eph.record is obj

    # Core state arrays: shape (n_steps, 3), float64.
    assert eph.position_km.shape == (n_steps, 3)
    assert eph.velocity_km_s.shape == (n_steps, 3)
    assert eph.position_km.dtype.name == "float64"
    assert eph.velocity_km_s.dtype.name == "float64"

    # Time grid: one axis, length n_steps.
    assert eph.times.shape == (n_steps,)

    # Accessors return the shapes their docstrings promise.
    assert eph.gcrs().shape == (n_steps, 3)
    assert eph.itrf().shape == (n_steps, 3)
    lat, lon, alt = eph.subpoint()
    assert lat.shape == (n_steps,)
    assert lon.shape == (n_steps,)
    assert alt.shape == (n_steps,)
    assert eph.altitude_km().shape == (n_steps,)


def test_ingested_catalog_object_single_sample_grid() -> None:
    obj = _iss_catalog_object()
    start = datetime(2008, 9, 20, 12, 25, tzinfo=timezone.utc)

    eph = propagate_one(obj, start, hours=0, step_seconds=60)

    assert eph.position_km.shape == (1, 3)
    assert eph.velocity_km_s.shape == (1, 3)
    assert eph.times.shape == (1,)
    assert eph.altitude_km().shape == (1,)
