"""Physical-plausibility checks on a 24-hour ISS propagation.

Not a reference-vector test -- it asserts against model-independent
physical facts about a known LEO orbit, the kind of check that catches a
km/metre unit slip, a wrong output frame, or a decayed-orbit blow-up even
when no external ephemeris is on hand:

* geocentric radius stays in a tight LEO band,
* speed stays in the vis-viva band for that radius,
* sub-satellite latitude never exceeds the orbital inclination (a rigorous
  geometric bound), give or take a small margin,
* the perigee-to-perigee period matches the ~92.9 min implied by the TLE
  mean motion (1440 / 15.4956 = 92.93 min Keplerian).

The ISS elements are the repo's shared illustrative TLE (see
``tests/test_propagate.py``). The radius/speed bounds are the measured
envelope of this orbit with a few km / tens of mm/s of margin -- wider than
a naive read of the mean perigee/apogee altitudes, because the
*instantaneous* geocentric radius and speed oscillate by ~20 km / ~25 mm/s
over one revolution (J2 plus the eccentric anomaly variation), which the
mean apogee/perigee understates.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from prahari_orbital.models import CatalogObject, ObjectType, RcsSize
from prahari_orbital.propagate import propagate_one

ISS = CatalogObject(
    norad_id=25544,
    name="ISS (ZARYA)",
    tle_line1="1 25544U 98067A   26236.55742000  .00016717  00000-0  10270-3 0  9008",
    tle_line2="2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49560829 12345",
    epoch="2026-08-24T13:22:41Z",
    epoch_age_hours=0.0,
    object_type=ObjectType.PAYLOAD,
    rcs_size=RcsSize.LARGE,
    radius_m=55.0,
    perigee_km=413.2,
    apogee_km=421.8,
    inclination_deg=51.6416,
)

START = datetime(2026, 8, 24, 13, 22, 41, tzinfo=UTC)
STEP_SECONDS = 30
HOURS = 24

RADIUS_MIN_KM, RADIUS_MAX_KM = 6770.0, 6810.0
SPEED_MIN_KM_S, SPEED_MAX_KM_S = 7.63, 7.69
PERIOD_MIN_MIN, PERIOD_MAX_MIN = 92.0, 93.0
LAT_MARGIN_DEG = 0.5


@pytest.fixture(scope="module")
def ephemeris():
    return propagate_one(ISS, START, HOURS, STEP_SECONDS)


def test_geocentric_radius_stays_in_leo_band(ephemeris) -> None:
    radius_km = np.linalg.norm(ephemeris.position_km, axis=1)
    assert RADIUS_MIN_KM < radius_km.min() and radius_km.max() < RADIUS_MAX_KM, (
        f"radius range [{radius_km.min():.3f}, {radius_km.max():.3f}] km "
        f"outside [{RADIUS_MIN_KM}, {RADIUS_MAX_KM}] km"
    )


def test_speed_stays_in_vis_viva_band(ephemeris) -> None:
    speed_km_s = np.linalg.norm(ephemeris.velocity_km_s, axis=1)
    assert SPEED_MIN_KM_S < speed_km_s.min() and speed_km_s.max() < SPEED_MAX_KM_S, (
        f"speed range [{speed_km_s.min():.5f}, {speed_km_s.max():.5f}] km/s "
        f"outside [{SPEED_MIN_KM_S}, {SPEED_MAX_KM_S}] km/s"
    )


def test_latitude_never_exceeds_inclination(ephemeris) -> None:
    lat_deg, _lon_deg, _alt_km = ephemeris.subpoint()
    max_abs_lat = float(np.abs(lat_deg).max())
    assert max_abs_lat <= ISS.inclination_deg + LAT_MARGIN_DEG, (
        f"max |latitude| {max_abs_lat:.4f} deg exceeds inclination "
        f"{ISS.inclination_deg} + {LAT_MARGIN_DEG} deg margin"
    )


def test_orbital_period_between_altitude_minima(ephemeris) -> None:
    # An altitude minimum is perigee, i.e. the instant the radial component
    # of velocity crosses zero from negative to positive. Locate each
    # crossing by linear interpolation and take successive differences.
    pos_km = ephemeris.position_km
    vel_km_s = ephemeris.velocity_km_s
    radius_km = np.linalg.norm(pos_km, axis=1)
    radial_speed_km_s = np.sum(pos_km * vel_km_s, axis=1) / radius_km
    t_seconds = np.arange(radius_km.shape[0]) * STEP_SECONDS

    crossings_s: list[float] = []
    for i in range(radial_speed_km_s.shape[0] - 1):
        before, after = radial_speed_km_s[i], radial_speed_km_s[i + 1]
        if before < 0.0 <= after:
            frac = -before / (after - before)
            crossings_s.append(float(t_seconds[i] + frac * STEP_SECONDS))

    assert len(crossings_s) >= 10, f"only {len(crossings_s)} perigee crossings in 24 h"

    periods_min = np.diff(np.asarray(crossings_s)) / 60.0
    assert PERIOD_MIN_MIN < periods_min.min() and periods_min.max() < PERIOD_MAX_MIN, (
        f"period range [{periods_min.min():.4f}, {periods_min.max():.4f}] min "
        f"outside [{PERIOD_MIN_MIN}, {PERIOD_MAX_MIN}] min"
    )
