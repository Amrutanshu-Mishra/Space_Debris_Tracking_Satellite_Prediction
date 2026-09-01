"""Monotonicity, boundary, and schema-conformance tests for scoring.py.

The risk_score / risk_tier / confidence_band functions are pure and cheap, so
these run without any propagation. The export tests validate real
:class:`ConjunctionEvent`\\ s against the frozen
``contracts/schemas/conjunction.schema.json`` — the same file scoring.py
validates against, loaded here independently.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from skyfield.api import load

from prahari_orbital.models import CatalogObject, ObjectType, RcsSize, RiskTier
from prahari_orbital.scoring import (
    RISK_TIER_AMBER_THRESHOLD,
    RISK_TIER_RED_THRESHOLD,
    compute_pc,
    confidence_band,
    constellation_of,
    export_events,
    is_intra_constellation,
    risk_score,
    risk_tier,
    score,
    validate_event_dict,
)
from prahari_orbital.screen import ScreeningResult

SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "schemas"
    / "conjunction.schema.json"
)
_TS = load.timescale()
_TCA = _TS.from_datetime(datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC))
_SCREENED_AT = datetime(2026, 8, 29, 12, 5, 0, tzinfo=UTC)


def _object(
    norad_id: int,
    *,
    epoch_age_hours: float = 10.0,
    perigee_km: float = 700.0,
    radius_m: float = 2.0,
    name: str | None = None,
    object_type: ObjectType = ObjectType.PAYLOAD,
) -> CatalogObject:
    return CatalogObject(
        norad_id=norad_id,
        name=name if name is not None else f"SCORE-TEST-{norad_id}",
        tle_line1="1 " + "0" * 67,
        tle_line2="2 " + "0" * 67,
        epoch=datetime(2026, 8, 29, 0, 0, 0, tzinfo=UTC),
        epoch_age_hours=epoch_age_hours,
        object_type=object_type,
        rcs_size=RcsSize.MEDIUM,
        radius_m=radius_m,
        perigee_km=perigee_km,
        apogee_km=perigee_km + 20.0,
        inclination_deg=51.6,
    )


def _result(
    *,
    miss_distance_km: float,
    relative_velocity_km_s: float = 8.0,
    primary_norad_id: int = 40001,
    secondary_norad_id: int = 40002,
) -> ScreeningResult:
    # Split the miss vector arbitrarily but consistently across the RIC axes so
    # radial^2 + in_track^2 + cross_track^2 == miss_distance^2.
    component = miss_distance_km / (3.0**0.5)
    return ScreeningResult(
        primary_norad_id=primary_norad_id,
        secondary_norad_id=secondary_norad_id,
        tca=_TCA,
        miss_distance_km=miss_distance_km,
        relative_velocity_km_s=relative_velocity_km_s,
        radial_km=component,
        in_track_km=component,
        cross_track_km=component,
    )


# --------------------------------------------------------------------------- #
# risk_score monotonicity                                                     #
# --------------------------------------------------------------------------- #


def test_risk_score_never_decreases_as_miss_distance_falls() -> None:
    miss_grid = [15.0, 12.0, 10.0, 9.0, 7.5, 5.0, 3.0, 1.0, 0.25, 0.0]
    scores = [risk_score(m, 8.0, 4.0) for m in miss_grid]
    assert scores == sorted(scores), scores  # non-decreasing as miss shrinks


def test_risk_score_never_decreases_as_relative_velocity_rises() -> None:
    vel_grid = [0.0, 0.5, 2.0, 5.0, 9.0, 12.0, 15.0, 18.0, 40.0]
    scores = [risk_score(3.0, v, 4.0) for v in vel_grid]
    assert scores == sorted(scores), scores


def test_risk_score_never_decreases_as_combined_radius_rises() -> None:
    radius_grid = [0.0, 1.0, 5.0, 20.0, 50.0, 100.0, 250.0]
    scores = [risk_score(3.0, 8.0, r) for r in radius_grid]
    assert scores == sorted(scores), scores


def test_risk_score_stays_in_unit_interval_at_extremes() -> None:
    assert 0.0 <= risk_score(0.0, 1_000.0, 10_000.0) <= 1.0
    assert 0.0 <= risk_score(10_000.0, 0.0, 0.0) <= 1.0
    # All three factors saturated -> exactly the sum of the weights == 1.0.
    assert risk_score(0.0, 100.0, 1_000.0) == pytest.approx(1.0)
    # Nothing dangerous -> exactly 0.0.
    assert risk_score(10.0, 0.0, 0.0) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# risk_tier — from the score alone                                            #
# --------------------------------------------------------------------------- #


def test_risk_tier_boundaries() -> None:
    assert risk_tier(RISK_TIER_RED_THRESHOLD) == RiskTier.RED
    assert risk_tier(1.0) == RiskTier.RED
    assert risk_tier(RISK_TIER_RED_THRESHOLD - 1e-9) == RiskTier.AMBER
    assert risk_tier(RISK_TIER_AMBER_THRESHOLD) == RiskTier.AMBER
    assert risk_tier(RISK_TIER_AMBER_THRESHOLD - 1e-9) == RiskTier.GREEN
    assert risk_tier(0.0) == RiskTier.GREEN


def test_risk_tier_is_monotonic_in_score() -> None:
    tiers = [risk_tier(s / 100.0) for s in range(101)]
    order = {RiskTier.GREEN: 0, RiskTier.AMBER: 1, RiskTier.RED: 2}
    ranks = [order[t] for t in tiers]
    assert ranks == sorted(ranks)


# --------------------------------------------------------------------------- #
# confidence                                                                  #
# --------------------------------------------------------------------------- #


def test_confidence_is_monotonic_decreasing_in_epoch_age() -> None:
    ages = [0.0, 12.0, 24.0, 48.0, 96.0, 168.0, 240.0, 500.0, 1_000.0]
    confidences = [confidence_band(age, 700.0)[0] for age in ages]
    assert confidences == sorted(confidences, reverse=True), confidences


def test_confidence_boundary_cases() -> None:
    # Fresh epoch, high orbit: no penalties at all.
    assert confidence_band(0.0, 700.0)[0] == pytest.approx(1.0)
    # Fresh epoch, low orbit: only the flat 0.20 drag penalty.
    assert confidence_band(0.0, 450.0)[0] == pytest.approx(0.80)
    # 500 h >> 168 h: age term saturates at 0.70, high orbit -> 1 - 0.70.
    assert confidence_band(500.0, 700.0)[0] == pytest.approx(0.30)
    # 500 h and low orbit: 1 - 0.70 - 0.20 = 0.10.
    assert confidence_band(500.0, 450.0)[0] == pytest.approx(0.10)
    # The age term saturates at 0.70, so 0.10 is the lowest the formula can
    # produce; the 0.05 clip is a defensive floor, and confidence never dips
    # below it however extreme the inputs.
    worst = confidence_band(10_000.0, 100.0)[0]
    assert worst == pytest.approx(0.10)
    assert worst >= 0.05


def test_confidence_note_names_age_and_low_orbit_penalty() -> None:
    _, note_low = confidence_band(200.0, 420.0)
    assert "200 h" in note_low
    assert "500 km" in note_low  # the low-orbit drag penalty is spelled out

    _, note_high = confidence_band(30.0, 800.0)
    assert "30 h" in note_high

    # A user-facing sentence, and never the word "probability".
    for note in (note_low, note_high):
        assert note[0].isupper() and note.endswith(".")
        assert "probab" not in note.lower()


# --------------------------------------------------------------------------- #
# score() boundary cases                                                      #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("miss_distance_km", "epoch_age_hours"),
    [
        (0.0, 0.0),
        (0.0, 500.0),
        (12.0, 0.0),  # above the 10 km proximity cutoff
        (12.0, 500.0),
        (10.0, 168.0),  # exactly on both cutoffs
    ],
)
def test_score_boundary_cases_validate_against_schema(
    miss_distance_km: float,
    epoch_age_hours: float,
    schema: dict,
) -> None:
    primary = _object(40001, epoch_age_hours=epoch_age_hours, perigee_km=480.0)
    secondary = _object(40002, epoch_age_hours=max(epoch_age_hours - 50.0, 0.0))
    candidate = _result(miss_distance_km=miss_distance_km)

    event = score(candidate, primary, secondary, screened_at=_SCREENED_AT)

    assert 0.0 <= event.risk_score <= 1.0
    assert 0.05 <= event.confidence <= 1.0
    assert event.combined_radius_m == pytest.approx(primary.radius_m + secondary.radius_m)
    assert event.max_epoch_age_hours == pytest.approx(
        max(primary.epoch_age_hours, secondary.epoch_age_hours)
    )
    if miss_distance_km >= 10.0:
        # proximity term is 0; only energy + size can contribute.
        assert event.risk_score <= 0.30 + 0.10 + 1e-9

    Draft7Validator(schema, format_checker=Draft7Validator.FORMAT_CHECKER).validate(
        event.model_dump(mode="json")
    )


def test_score_rejects_mismatched_candidate_ids() -> None:
    primary = _object(1)
    secondary = _object(2)
    candidate = _result(miss_distance_km=1.0)  # ids 40001 / 40002
    with pytest.raises(ValueError, match="do not match"):
        score(candidate, primary, secondary)


def test_score_rejects_naive_screened_at() -> None:
    primary = _object(40001)
    secondary = _object(40002)
    candidate = _result(miss_distance_km=1.0)
    naive = datetime(2026, 8, 29, 12, 0, 0)  # noqa: DTZ001 -- deliberately naive
    with pytest.raises(ValueError, match="timezone-aware"):
        score(candidate, primary, secondary, screened_at=naive)


# --------------------------------------------------------------------------- #
# intra-constellation flagging                                                #
# --------------------------------------------------------------------------- #


def test_constellation_of_matches_known_prefixes_case_insensitively() -> None:
    assert constellation_of("STARLINK-1234") == "STARLINK"
    assert constellation_of("  starlink-1234") == "STARLINK"
    assert constellation_of("OneWeb-0012") == "ONEWEB"
    assert constellation_of("IRIDIUM 33 DEB") == "IRIDIUM"  # type gate is elsewhere
    assert constellation_of("ISS (ZARYA)") is None
    assert constellation_of("STARLINKX") == "STARLINK"  # prefix only; acceptable


def test_is_intra_constellation_same_constellation_payloads() -> None:
    a = _object(40001, name="STARLINK-1234")
    b = _object(40002, name="STARLINK-5678")
    assert is_intra_constellation(a, b) is True


def test_is_intra_constellation_false_across_constellations_and_types() -> None:
    starlink = _object(1, name="STARLINK-1")
    oneweb = _object(2, name="ONEWEB-0002")
    assert is_intra_constellation(starlink, oneweb) is False

    iridium_payload = _object(3, name="IRIDIUM 33")
    iridium_debris = _object(4, name="IRIDIUM 33 DEB", object_type=ObjectType.DEBRIS)
    assert is_intra_constellation(iridium_payload, iridium_debris) is False

    assert is_intra_constellation(_object(5, name="ISS (ZARYA)"), _object(6, name="HST")) is False


def test_score_sets_intra_constellation_flag() -> None:
    candidate = _result(miss_distance_km=3.0, primary_norad_id=1, secondary_norad_id=2)
    starlink_pair = score(
        candidate,
        _object(1, name="STARLINK-1000"),
        _object(2, name="STARLINK-2000"),
        screened_at=_SCREENED_AT,
    )
    assert starlink_pair.intra_constellation is True

    mixed = score(
        candidate,
        _object(1, name="STARLINK-1000"),
        _object(2, name="COSMOS 2251 DEB", object_type=ObjectType.DEBRIS),
        screened_at=_SCREENED_AT,
    )
    assert mixed.intra_constellation is False


# --------------------------------------------------------------------------- #
# export_events                                                               #
# --------------------------------------------------------------------------- #


def _sample_events() -> list:
    events = []
    for i, (miss, vel, age, perigee) in enumerate(
        [
            (0.2, 13.0, 4.0, 480.0),   # ~RED, low orbit
            (4.0, 9.0, 60.0, 550.0),   # ~AMBER
            (9.5, 1.0, 200.0, 700.0),  # ~GREEN, stale
        ]
    ):
        primary = _object(50000 + 2 * i, epoch_age_hours=age, perigee_km=perigee)
        secondary = _object(50001 + 2 * i, epoch_age_hours=age / 2.0, perigee_km=perigee + 300.0)
        events.append(
            score(
                _result(
                    miss_distance_km=miss,
                    relative_velocity_km_s=vel,
                    primary_norad_id=primary.norad_id,
                    secondary_norad_id=secondary.norad_id,
                ),
                primary,
                secondary,
                screened_at=_SCREENED_AT,
            )
        )
    return events


def test_exported_events_all_validate_against_frozen_schema(
    tmp_path: Path,
    schema: dict,
) -> None:
    out = export_events(_sample_events(), tmp_path / "conjunctions.json")
    written = json.loads(out.read_text(encoding="utf-8"))

    assert isinstance(written, list) and len(written) == 3
    validator = Draft7Validator(schema, format_checker=Draft7Validator.FORMAT_CHECKER)
    for event_dict in written:
        validator.validate(event_dict)


def test_export_is_atomic_on_a_bad_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import prahari_orbital.scoring as scoring_module

    good = _sample_events()[:1]
    original_payload = scoring_module._event_payload

    # Force the payload of the one event to carry a forbidden extra field;
    # additionalProperties:false in the schema must make export refuse.
    def _bad_payload(event: object) -> dict:
        return {**original_payload(event), "pc": 0.01}  # type: ignore[arg-type]

    monkeypatch.setattr(scoring_module, "_event_payload", _bad_payload)
    target = tmp_path / "should_not_exist.json"
    with pytest.raises(ValueError, match="schema violation"):
        export_events(good, target)
    assert not target.exists()


def test_validate_event_dict_flags_missing_required_and_extra_fields() -> None:
    assert validate_event_dict({}) != []  # every required field missing

    events = _sample_events()
    payload = events[0].model_dump(mode="json")
    assert validate_event_dict(payload) == []

    with_pc = {**payload, "pc": 0.5}
    problems = validate_event_dict(with_pc)
    assert any("pc" in p or "additional" in p.lower() for p in problems)

    out_of_range = {**payload, "risk_score": 1.5}
    assert validate_event_dict(out_of_range) != []


def test_no_pc_or_probability_anywhere_in_exported_output(tmp_path: Path) -> None:
    out = export_events(_sample_events(), tmp_path / "conjunctions.json")
    raw = out.read_text(encoding="utf-8")

    assert "probability" not in raw.lower()
    assert "probability_of_collision" not in raw

    def _keys(node: object) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            for key, value in node.items():
                found.add(key)
                found |= _keys(value)
        elif isinstance(node, list):
            for item in node:
                found |= _keys(item)
        return found

    all_keys = _keys(json.loads(raw))
    assert "pc" not in all_keys
    assert not any("probab" in k.lower() for k in all_keys)


# --------------------------------------------------------------------------- #
# the anti-Pc guard                                                           #
# --------------------------------------------------------------------------- #


def test_compute_pc_is_disabled() -> None:
    """This must never silently start returning a number — see module docstring."""
    with pytest.raises(NotImplementedError):
        compute_pc()
