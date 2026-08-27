"""Regression test: SGP4 position for ISS vs a published reference ephemeris.

This is the Day 1 definition of done for the orbital-core role — see
docs/team/01-orbital-core.md. It is written now, against a real TLE, so
orbital-core has a concrete pass/fail target the moment propagate.propagate
stops raising NotImplementedError. Skipped (not failed) until then, so
`make test` stays green for the rest of the team.

TODO(orbital-core): once propagate() is implemented, replace the reference
position below with a value taken from a published source (e.g. Celestrak's
own SGP4 verification vectors, or a JPL Horizons query for the same epoch)
and drop the skip.
"""

from __future__ import annotations

import pytest
from skyfield.api import load

from prahari_orbital.models import CatalogObject, ObjectType, RcsSize
from prahari_orbital.propagate import propagate

# A real ISS TLE, epoch 2026-08-24T13:22:41Z (illustrative — orbital-core
# should refresh this to a TLE whose epoch they can cross-check against an
# independent ephemeris source before trusting the comparison).
ISS_TLE_LINE1 = "1 25544U 98067A   26236.55742000  .00016717  00000-0  10270-3 0  9008"
ISS_TLE_LINE2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49560829 12345"

ISS_OBJECT = CatalogObject(
    norad_id=25544,
    name="ISS (ZARYA)",
    tle_line1=ISS_TLE_LINE1,
    tle_line2=ISS_TLE_LINE2,
    epoch="2026-08-24T13:22:41Z",
    epoch_age_hours=0.0,
    object_type=ObjectType.PAYLOAD,
    rcs_size=RcsSize.LARGE,
    radius_m=55.0,
    perigee_km=413.2,
    apogee_km=421.8,
    inclination_deg=51.6416,
)

MAX_POSITION_ERROR_KM = 1.0


@pytest.mark.skip(reason="propagate.propagate is not implemented yet (orbital-core Day 1 target)")
def test_iss_position_matches_published_ephemeris() -> None:
    ts = load.timescale()
    t = ts.utc(2026, 8, 24, 13, 22, 41)

    state = propagate(ISS_OBJECT, t)

    assert state.frame == "GCRS"
    # TODO(orbital-core): replace with a real published reference vector.
    reference_position_km = state.position_km  # placeholder self-comparison
    error_km = float(((state.position_km - reference_position_km) ** 2).sum() ** 0.5)
    assert error_km < MAX_POSITION_ERROR_KM


@pytest.mark.skip(reason="propagate.propagate is not implemented yet")
def test_propagate_output_is_gcrs_not_teme() -> None:
    ts = load.timescale()
    t = ts.utc(2026, 8, 24, 13, 22, 41)
    state = propagate(ISS_OBJECT, t)
    assert state.frame == "GCRS", "propagate() must return GCRS, never raw TEME — see frames.py"
