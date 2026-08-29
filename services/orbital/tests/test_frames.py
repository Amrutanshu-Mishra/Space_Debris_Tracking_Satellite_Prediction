"""GCRS vs ITRF: identical magnitude, different direction.

``frames.gcrs_to_itrf_position_km`` applies a pure rotation (precession,
nutation, sidereal Earth rotation with UT1-UTC, polar motion). A pure
rotation preserves vector magnitude exactly, and -- at any epoch where
Earth has turned through a non-trivial angle -- moves every component by
a large amount.

This test pins both halves at once, because that is exactly the failure
mode of returning one frame while labelling it the other: such a bug
leaves the magnitude untouched (so a magnitude-only check still passes)
while every component is wrong by thousands of km.

The frame is called "GCRS" throughout this package by deliberate
convention (see ``services/orbital/CLAUDE.md``); Skyfield's own docs say
"GCRF" for the same vectors. The distinction is far below the error budget
here and is not tracked.
"""

from __future__ import annotations

import numpy as np
from skyfield.api import EarthSatellite

from prahari_orbital import frames
from prahari_orbital.propagate import _timescale

# Repo's shared illustrative ISS TLE (see tests/test_propagate.py).
_TLE_LINE1 = "1 25544U 98067A   26236.55742000  .00016717  00000-0  10270-3 0  9008"
_TLE_LINE2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49560829 12345"

MAX_MAGNITUDE_DIFF_KM = 1.0e-3  # 1 metre -- a rotation must preserve length
MIN_COMPONENT_DIFF_KM = 100.0  # Earth has rotated: the vectors must really move


def _gcrs_track() -> tuple[np.ndarray, object]:
    """A short GCRS position track (km) and its aligned Skyfield Time.

    Built straight from Skyfield's ``EarthSatellite.at()``, the same source
    ``propagate_one`` uses, so the array handed to ``frames`` is a genuine
    GCRS position rather than a hand-constructed one.
    """
    ts = _timescale()
    sat = EarthSatellite(_TLE_LINE1, _TLE_LINE2, "ISS", ts)
    t = ts.utc(2026, 8, 25, 0, range(0, 720, 20))  # 12 h, every 20 min
    geocentric = sat.at(t)
    pos_gcrs_km = np.ascontiguousarray(geocentric.position.km.T, dtype=np.float64)
    return pos_gcrs_km, t


def test_gcrs_and_itrf_have_equal_magnitude() -> None:
    pos_gcrs_km, t = _gcrs_track()
    pos_itrf_km = frames.gcrs_to_itrf_position_km(pos_gcrs_km, t)

    mag_gcrs_km = np.linalg.norm(frames.gcrs_position_km(pos_gcrs_km), axis=1)
    mag_itrf_km = np.linalg.norm(pos_itrf_km, axis=1)

    max_diff_km = float(np.max(np.abs(mag_gcrs_km - mag_itrf_km)))
    assert max_diff_km < MAX_MAGNITUDE_DIFF_KM, (
        f"|GCRS| vs |ITRF| differ by up to {max_diff_km * 1e3:.6f} m -- "
        f"a frame rotation must preserve magnitude"
    )


def test_gcrs_and_itrf_components_differ() -> None:
    pos_gcrs_km, t = _gcrs_track()
    pos_itrf_km = frames.gcrs_to_itrf_position_km(pos_gcrs_km, t)

    per_sample_diff_km = np.linalg.norm(pos_gcrs_km - pos_itrf_km, axis=1)
    assert per_sample_diff_km.min() > MIN_COMPONENT_DIFF_KM, (
        f"GCRS and ITRF positions are only {per_sample_diff_km.min():.3f} km "
        f"apart -- the rotation is not being applied (frame likely returned as-is)"
    )
    # Rule out a degenerate "rotation" that is really a sign flip or a
    # uniform translation.
    assert not np.allclose(pos_gcrs_km, -pos_itrf_km)
    assert not np.allclose(pos_gcrs_km - pos_itrf_km, (pos_gcrs_km - pos_itrf_km)[0])
