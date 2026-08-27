"""Monotonicity and boundary-case tests for risk_score / risk_tier / confidence_band.

These are cheap, pure-function tests (no propagation required) so they can
be written and passed before propagate.py or screen.py exist at all.
"""

from __future__ import annotations

import pytest

from prahari_orbital.models import RiskTier
from prahari_orbital.scoring import (
    RISK_TIER_AMBER_THRESHOLD,
    RISK_TIER_RED_THRESHOLD,
    compute_pc,
    risk_score,
    risk_tier,
)


@pytest.mark.skip(reason="risk_score is not implemented yet (screening-scoring Day 2 target)")
def test_risk_score_decreases_with_miss_distance() -> None:
    close = risk_score(miss_distance_km=0.1, relative_velocity_km_s=10.0)
    far = risk_score(miss_distance_km=10.0, relative_velocity_km_s=10.0)
    assert close > far


@pytest.mark.skip(reason="risk_score is not implemented yet")
def test_risk_score_increases_with_relative_velocity() -> None:
    slow = risk_score(miss_distance_km=1.0, relative_velocity_km_s=1.0)
    fast = risk_score(miss_distance_km=1.0, relative_velocity_km_s=14.0)
    assert fast > slow


@pytest.mark.skip(reason="risk_score is not implemented yet")
def test_risk_score_bounded_zero_one() -> None:
    assert 0.0 <= risk_score(miss_distance_km=0.0, relative_velocity_km_s=100.0) <= 1.0
    assert 0.0 <= risk_score(miss_distance_km=1000.0, relative_velocity_km_s=0.0) <= 1.0


@pytest.mark.skip(reason="risk_tier is not implemented yet")
def test_risk_tier_boundaries() -> None:
    assert risk_tier(RISK_TIER_RED_THRESHOLD) == RiskTier.RED
    assert risk_tier(RISK_TIER_RED_THRESHOLD - 0.01) != RiskTier.RED
    assert risk_tier(RISK_TIER_AMBER_THRESHOLD) in (RiskTier.AMBER, RiskTier.RED)
    assert risk_tier(0.0) == RiskTier.GREEN


@pytest.mark.skip(reason="confidence_band is not implemented yet (screening-scoring Day 2/3 target)")
def test_confidence_decreases_with_epoch_age() -> None:
    raise NotImplementedError("TODO(screening-scoring): fresh-epoch pair vs stale-epoch pair, assert confidence ordering")


def test_compute_pc_is_disabled() -> None:
    """This must never silently start returning a number — see module docstring."""
    with pytest.raises(NotImplementedError):
        compute_pc()
