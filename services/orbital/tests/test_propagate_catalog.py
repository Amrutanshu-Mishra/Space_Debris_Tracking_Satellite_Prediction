"""Batch propagation: ``propagate_catalog`` / ``CatalogEphemeris``.

The vectorised ``SatrecArray`` path is checked against the already-trusted
single-object path (``propagate_one``, itself verified against Vallado in
``test_propagate_vectors.py``): the batch result for each surviving object
must equal what ``propagate_one`` produces for that object alone. That is a
cross-implementation check, not a self-comparison -- the two share no code
below ``frames``.

Also pinned here: failed objects are excluded from the arrays (never
zero-filled) and reported in ``failures``; the ``dtype`` switch; and the
``save_npz`` / ``load_npz`` round-trip.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from prahari_orbital.models import CatalogObject, ObjectType, RcsSize
from prahari_orbital.propagate import (
    CatalogEphemeris,
    propagate_catalog,
    propagate_one,
)

START = datetime(2026, 8, 25, 0, 0, 0, tzinfo=UTC)
HOURS = 6
STEP_SECONDS = 60


def _obj(norad_id: int, line1: str, line2: str, inclination_deg: float = 51.0) -> CatalogObject:
    return CatalogObject(
        norad_id=norad_id,
        name=str(norad_id),
        tle_line1=line1,
        tle_line2=line2,
        epoch="2026-08-24T00:00:00Z",
        epoch_age_hours=0.0,
        object_type=ObjectType.DEBRIS,
        rcs_size=RcsSize.MEDIUM,
        radius_m=1.0,
        perigee_km=400.0,
        apogee_km=420.0,
        inclination_deg=inclination_deg,
    )


# Two healthy objects (a LEO and Vallado's Vanguard case) + one that SGP4
# cannot propagate (22312, given in SGP4-VER.TLE as "decayed 2006-04-04").
ISS = _obj(
    25544,
    "1 25544U 98067A   26236.55742000  .00016717  00000-0  10270-3 0  9008",
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49560829 12345",
    inclination_deg=51.6416,
)
VANGUARD = _obj(
    5,
    "1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753",
    "2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667",
    inclination_deg=34.2682,
)
DECAYED = _obj(
    22312,
    "1 22312U 93002D   06094.46235912  .99999999  81888-5  49949-3 0  3953",
    "2 22312  62.1486  77.4698 0308723 267.9229  88.7392 15.95744531 98783",
    inclination_deg=62.1486,
)
MALFORMED = _obj(
    999999,
    "1 999999U not a real tle line",
    "2 999999 also nonsense",
)


@pytest.fixture(scope="module")
def catalog() -> CatalogEphemeris:
    return propagate_catalog([ISS, VANGUARD, DECAYED], START, HOURS, STEP_SECONDS)


def test_shape_and_frame_metadata(catalog: CatalogEphemeris) -> None:
    n_steps = HOURS * 3600 // STEP_SECONDS + 1
    assert catalog.position_km.shape == (2, n_steps, 3)
    assert catalog.velocity_km_s.shape == (2, n_steps, 3)
    assert catalog.norad_ids.shape == (2,)
    assert catalog.times.tt.shape == (n_steps,)
    assert catalog.position_km.dtype == np.float64


def test_batch_matches_single_object_path(catalog: CatalogEphemeris) -> None:
    for row, norad_id in enumerate(catalog.norad_ids.tolist()):
        record = {25544: ISS, 5: VANGUARD}[norad_id]
        single = propagate_one(record, START, HOURS, STEP_SECONDS)
        pos_err_m = np.linalg.norm(
            catalog.position_km[row] - single.position_km, axis=1
        ).max() * 1e3
        vel_err_mm_s = np.linalg.norm(
            catalog.velocity_km_s[row] - single.velocity_km_s, axis=1
        ).max() * 1e6
        assert pos_err_m < 1e-3, f"NORAD {norad_id}: batch vs single {pos_err_m:.3e} m"
        assert vel_err_mm_s < 1e-3, f"NORAD {norad_id}: {vel_err_mm_s:.3e} mm/s"


def test_failed_object_excluded_and_reported(catalog: CatalogEphemeris) -> None:
    assert DECAYED.norad_id not in catalog.norad_ids.tolist()
    failed_ids = [nid for nid, _ in catalog.failures]
    assert failed_ids == [DECAYED.norad_id]
    assert "error code" in catalog.failures[0][1]
    # nothing zero-filled: every surviving sample is a real orbital radius
    radius_km = np.linalg.norm(catalog.position_km, axis=2)
    assert radius_km.min() > 6500.0


def test_malformed_tle_is_a_failure_not_a_crash() -> None:
    # sgp4's C++ ``twoline2rv`` is very permissive: rather than raising, it
    # parses nonsense into a degenerate model that then returns an SGP4
    # error code. Either way the object must be excluded and reported --
    # never carried into the arrays.
    result = propagate_catalog([ISS, MALFORMED], START, HOURS, STEP_SECONDS)
    assert result.norad_ids.tolist() == [ISS.norad_id]
    assert [nid for nid, _ in result.failures] == [MALFORMED.norad_id]
    assert result.failures[0][1]  # a non-empty human-readable reason


def test_all_failed_raises() -> None:
    with pytest.raises(ValueError, match="all .* record.* failed|parseable TLE"):
        propagate_catalog([DECAYED], START, HOURS, STEP_SECONDS)


def test_dtype_float32(catalog: CatalogEphemeris) -> None:
    result = propagate_catalog(
        [ISS, VANGUARD, DECAYED], START, HOURS, STEP_SECONDS, dtype=np.float32
    )
    assert result.position_km.dtype == np.float32
    assert result.velocity_km_s.dtype == np.float32
    # float32 of a ~6800 km magnitude keeps ~0.5 m; the physics is unchanged.
    deviation_m = np.abs(
        result.position_km.astype(np.float64) - catalog.position_km
    ).max() * 1e3
    assert deviation_m < 2.0


def test_rejects_bad_arguments() -> None:
    naive = datetime(2026, 8, 25, 0, 0, 0)  # noqa: DTZ001 -- deliberately naive
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        propagate_catalog([ISS], naive, HOURS, STEP_SECONDS)
    with pytest.raises(ValueError, match="'dtype'"):
        propagate_catalog([ISS], START, HOURS, STEP_SECONDS, dtype=np.int32)
    with pytest.raises(ValueError, match="'records' is empty"):
        propagate_catalog([], START, HOURS, STEP_SECONDS)
    with pytest.raises(ValueError, match="'step_seconds'"):
        propagate_catalog([ISS], START, HOURS, 0)


def test_save_load_npz_round_trip(catalog: CatalogEphemeris, tmp_path) -> None:
    path = tmp_path / "catalog_ephemeris.npz"
    catalog.save_npz(path)
    restored = CatalogEphemeris.load_npz(path)

    assert np.array_equal(restored.norad_ids, catalog.norad_ids)
    assert np.array_equal(restored.position_km, catalog.position_km)
    assert np.array_equal(restored.velocity_km_s, catalog.velocity_km_s)
    assert restored.position_km.dtype == catalog.position_km.dtype
    assert restored.failures == catalog.failures
    # time grid survives losslessly (whole + tt_fraction pair, not a single float)
    assert np.abs(restored.times.tt - catalog.times.tt).max() == 0.0


def test_save_load_npz_preserves_float32(catalog: CatalogEphemeris, tmp_path) -> None:
    result = propagate_catalog(
        [ISS, VANGUARD], START, HOURS, STEP_SECONDS, dtype=np.float32
    )
    path = tmp_path / "f32.npz"
    result.save_npz(path)
    restored = CatalogEphemeris.load_npz(path)
    assert restored.position_km.dtype == np.float32
    assert np.array_equal(restored.position_km, result.position_km)
