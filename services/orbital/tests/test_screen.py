"""Fine-screening correctness: refinement, RIC decomposition, multiplicity.

The two objects here are synthetic but their TLEs are real (built with
``sgp4.Satrec.sgp4init`` and exported with ``sgp4.exporter.export_tle``, so
``screen.py`` propagates them through the same SGP4 path as any catalogue
object). They share an orbit plane (same inclination, RAAN, epoch) and differ
only in semi-major axis by ~320 km, which makes the trailing object lap the
leading one roughly once a day: over a 72 h window the pair has three
distinct close approaches, each bottoming out near the 320 km radial gap.
That geometry is analytic, not a screen-vs-screen comparison — it is known
from the construction, independently of anything ``screen.py`` computes.

Assertions:
* every refined miss distance is <= the coarse-grid separation at the local
  minimum it was refined from (refinement can only find a closer approach);
* the RIC components satisfy radial^2 + in_track^2 + cross_track^2 ==
  miss_distance^2 to within a metre (the RIC axes are orthonormal);
* the pair yields more than one ScreeningResult (all three approaches, not
  just the global minimum).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pytest
from sgp4.api import WGS72, Satrec
from sgp4.exporter import export_tle
from skyfield.api import load

from prahari_orbital.filters import CandidatePair
from prahari_orbital.models import CatalogObject, ObjectType, RcsSize
from prahari_orbital.propagate import propagate_one
from prahari_orbital.screen import COARSE_STEP_SECONDS, screen_candidates

EARTH_RADIUS_KM = 6371.0
MU_KM3_S2 = 398600.4418
JD_1949_12_31 = 2433281.5

START = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
WINDOW_HOURS = 72.0
#: Loose on purpose: the synthetic pair's approaches bottom out near their
#: ~320 km radial gap, so this must clear that to exercise the multi-minimum
#: + refinement path. Miss distance / RIC / multiplicity are all threshold-
#: independent invariants.
THRESHOLD_KM = 500.0

PRIMARY_ID = 90001
SECONDARY_ID = 90002
PRIMARY_SMA_KM = 6878.0
SECONDARY_SMA_KM = PRIMARY_SMA_KM + 320.0


def _make_object(
    norad_id: int,
    name: str,
    *,
    sma_km: float,
    ecc: float,
    inc_deg: float,
    raan_deg: float,
    argp_deg: float,
    mean_anomaly_deg: float,
    epoch: datetime,
) -> CatalogObject:
    """A CatalogObject backed by a real, freshly-exported TLE for given elements."""
    t = load.timescale().from_datetime(epoch)
    epoch_days = float(t.whole) + float(t.ut1_fraction) - JD_1949_12_31
    mean_motion_rad_min = math.sqrt(MU_KM3_S2 / sma_km**3) * 60.0

    sat = Satrec()
    sat.sgp4init(
        WGS72,
        "i",
        norad_id,
        epoch_days,
        0.0,  # bstar
        0.0,  # ndot
        0.0,  # nddot
        ecc,
        math.radians(argp_deg),
        math.radians(inc_deg),
        math.radians(mean_anomaly_deg),
        mean_motion_rad_min,
        math.radians(raan_deg),
    )
    sat.classification = "U"
    sat.intldesg = "25000A"
    sat.elnum = 1
    sat.revnum = 0
    line1, line2 = export_tle(sat)

    return CatalogObject(
        norad_id=norad_id,
        name=name,
        tle_line1=line1,
        tle_line2=line2,
        epoch=epoch,
        epoch_age_hours=0.0,
        object_type=ObjectType.PAYLOAD,
        rcs_size=RcsSize.MEDIUM,
        radius_m=1.0,
        perigee_km=sma_km * (1.0 - ecc) - EARTH_RADIUS_KM,
        apogee_km=sma_km * (1.0 + ecc) - EARTH_RADIUS_KM,
        inclination_deg=inc_deg,
    )


def _coarse_min_separations_km(
    primary: CatalogObject, secondary: CatalogObject
) -> np.ndarray:
    """Separation (km) of the pair on the same coarse grid screen.py samples."""
    hours = round(WINDOW_HOURS)
    step = round(COARSE_STEP_SECONDS)
    pos_p = propagate_one(primary, START, hours, step).position_km
    pos_s = propagate_one(secondary, START, hours, step).position_km
    delta = pos_s - pos_p
    return np.sqrt(np.einsum("ij,ij->i", delta, delta))


def _local_minima_indices(separation_km: np.ndarray, threshold_km: float) -> list[int]:
    """Interior local minima below threshold — mirrors screen._sub_threshold_local_minima."""
    interior = np.arange(1, separation_km.size - 1)
    here = separation_km[interior]
    is_min = (here < separation_km[interior - 1]) & (here <= separation_km[interior + 1])
    below = here < threshold_km
    return [int(i) for i in interior[is_min & below]]


@pytest.fixture(scope="module")
def coplanar_pair() -> tuple[CatalogObject, CatalogObject]:
    primary = _make_object(
        PRIMARY_ID,
        "SCREEN-TEST-PRIMARY",
        sma_km=PRIMARY_SMA_KM,
        ecc=1e-4,
        inc_deg=51.6,
        raan_deg=0.0,
        argp_deg=0.0,
        mean_anomaly_deg=0.0,
        epoch=START,
    )
    secondary = _make_object(
        SECONDARY_ID,
        "SCREEN-TEST-SECONDARY",
        sma_km=SECONDARY_SMA_KM,
        ecc=1e-4,
        inc_deg=51.6,
        raan_deg=0.0,
        argp_deg=0.0,
        mean_anomaly_deg=180.0,
        epoch=START,
    )
    return primary, secondary


@pytest.fixture(scope="module")
def screening_results(
    coplanar_pair: tuple[CatalogObject, CatalogObject],
) -> list:
    primary, secondary = coplanar_pair
    objects_by_id = {primary.norad_id: primary, secondary.norad_id: secondary}
    candidates = [
        CandidatePair(
            primary_norad_id=primary.norad_id,
            secondary_norad_id=secondary.norad_id,
            min_separation_km=float(_coarse_min_separations_km(primary, secondary).min()),
        )
    ]
    return screen_candidates(
        objects_by_id,
        candidates,
        start=START,
        window_hours=WINDOW_HOURS,
        threshold_km=THRESHOLD_KM,
    )


def test_multiple_approaches_yield_multiple_candidates(
    screening_results: list,
) -> None:
    assert len(screening_results) >= 2, (
        f"co-planar pair lapping once per day over {WINDOW_HOURS:g} h should "
        f"produce several approaches, got {len(screening_results)}"
    )
    assert all(
        {r.primary_norad_id, r.secondary_norad_id} == {PRIMARY_ID, SECONDARY_ID}
        for r in screening_results
    )
    tcas = [r.tca.tt for r in screening_results]
    assert tcas == sorted(tcas), "results should be chronological within a pair"


def test_refined_miss_not_worse_than_coarse_grid(
    coplanar_pair: tuple[CatalogObject, CatalogObject],
    screening_results: list,
) -> None:
    primary, secondary = coplanar_pair
    separation_km = _coarse_min_separations_km(primary, secondary)
    minima_idx = _local_minima_indices(separation_km, THRESHOLD_KM)

    assert len(screening_results) == len(minima_idx), (
        "one refined result per sub-threshold coarse local minimum"
    )
    for result, grid_idx in zip(screening_results, minima_idx):
        coarse_min_km = float(separation_km[grid_idx])
        assert result.miss_distance_km <= coarse_min_km + 1e-6, (
            f"refinement worsened the miss distance: refined "
            f"{result.miss_distance_km:.6f} km > coarse-grid "
            f"{coarse_min_km:.6f} km at grid index {grid_idx}"
        )


def test_ric_components_match_miss_distance(screening_results: list) -> None:
    assert screening_results
    for result in screening_results:
        rss_km = math.sqrt(
            result.radial_km**2 + result.in_track_km**2 + result.cross_track_km**2
        )
        assert math.isclose(rss_km, result.miss_distance_km, abs_tol=1e-3), (
            f"RIC components do not reconstruct the miss distance: "
            f"sqrt(R^2+I^2+C^2)={rss_km:.6f} km vs "
            f"miss_distance={result.miss_distance_km:.6f} km"
        )
