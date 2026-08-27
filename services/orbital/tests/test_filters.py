"""The coarse filter must never discard a true positive.

A false negative here is silent and catastrophic: a real close approach
just never reaches screen.py, and nobody is warned. These tests build a
synthetic pair with a known, engineered close approach and assert every
filter stage keeps the pair. False positives (keeping a pair that turns
out not to matter) are cheap — screen.py will discard it. False negatives
are not, so err aggressively toward this test suite over-testing the
"keep" direction.
"""

from __future__ import annotations

import pytest

from prahari_orbital.filters import apogee_perigee_prefilter
from prahari_orbital.models import CatalogObject, ObjectType, RcsSize


def _object(norad_id: int, perigee_km: float, apogee_km: float, inclination_deg: float = 51.6) -> CatalogObject:
    return CatalogObject(
        norad_id=norad_id,
        name=f"TEST-{norad_id}",
        tle_line1="1 " + "0" * 67,
        tle_line2="2 " + "0" * 67,
        epoch="2026-08-24T00:00:00Z",
        epoch_age_hours=1.0,
        object_type=ObjectType.DEBRIS,
        rcs_size=RcsSize.SMALL,
        radius_m=0.5,
        perigee_km=perigee_km,
        apogee_km=apogee_km,
        inclination_deg=inclination_deg,
    )


@pytest.mark.skip(reason="apogee_perigee_prefilter is not implemented yet (screening-scoring Day 1/2 target)")
def test_overlapping_altitude_bands_survive_prefilter() -> None:
    # Same orbital regime, altitude bands overlap by construction -> must survive.
    a = _object(norad_id=90001, perigee_km=400.0, apogee_km=420.0)
    b = _object(norad_id=90002, perigee_km=410.0, apogee_km=430.0)

    survivors = apogee_perigee_prefilter([a, b])

    assert (90001, 90002) in survivors or (90002, 90001) in survivors


@pytest.mark.skip(reason="apogee_perigee_prefilter is not implemented yet")
def test_non_overlapping_altitude_bands_are_discarded() -> None:
    # A's apogee (420) is far below B's perigee (35780, geostationary) -> can
    # never intersect within any reasonable margin -> safe to discard.
    a = _object(norad_id=90003, perigee_km=400.0, apogee_km=420.0)
    b = _object(norad_id=90004, perigee_km=35780.0, apogee_km=35790.0)

    survivors = apogee_perigee_prefilter([a, b])

    assert (90003, 90004) not in survivors
    assert (90004, 90003) not in survivors


@pytest.mark.skip(reason="coarse_filter end-to-end is not implemented yet")
def test_coarse_filter_prunes_more_than_99_99_percent() -> None:
    """This is the funnel-number contract behind CatalogStatus.pairs_fine_screened."""
    raise NotImplementedError("TODO(screening-scoring): build ~200-object synthetic catalogue, assert prune ratio")
