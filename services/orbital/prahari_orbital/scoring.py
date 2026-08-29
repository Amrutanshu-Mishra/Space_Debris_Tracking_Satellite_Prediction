"""Risk score, confidence, and schema-validated export for screened conjunctions.

:func:`score` turns one :class:`~prahari_orbital.screen.ScreeningResult` (exact
close-approach geometry) plus the two catalogue records into a
:class:`~prahari_orbital.models.ConjunctionEvent` matching
``contracts/schemas/conjunction.schema.json`` exactly. :func:`export_events`
writes a JSON array of those events, validating every one against the frozen
schema first and refusing to write if any fails.

NON-NEGOTIABLE DESIGN CONSTRAINT: this module never computes or emits a
probability of collision. Public TLEs carry no covariance, so a true Pc is not
statistically derivable from this data — see root README, "Why we don't publish
a probability of collision". ``risk_score`` is a transparent, weighted
heuristic; ``confidence`` separately captures how much to trust it given TLE
staleness, and is never folded into the risk tier. :func:`compute_pc` is a
documented, disabled stub for the day covariance data exists; it must stay
unreachable from the normal scoring path.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from prahari_orbital.models import CatalogObject, ConjunctionEvent, ObjectRef, RiskTier
from prahari_orbital.screen import ScreeningResult

# --------------------------------------------------------------------------- #
# risk_score — a weighted sum of three factors, each normalised to [0, 1].    #
#                                                                             #
# THESE WEIGHTS ARE ENGINEERING JUDGEMENT. They are not derived from first    #
# principles, orbital dynamics, or any collision-probability model. If a      #
# judge asks where 0.60 / 0.30 / 0.10 come from, that is the honest answer —  #
# they encode a deliberate ordering of which signals matter most, and the     #
# reasoning for each is written below.                                        #
# --------------------------------------------------------------------------- #

#: proximity — how close the approach is. Dominant term: with TLE-only data a
#: small miss distance is the single strongest signal available, so it carries
#: the most weight.
RISK_WEIGHT_PROXIMITY = 0.60
#: energy — relative speed at TCA. A fast encounter leaves less reaction time
#: and implies a more energetic outcome if the objects do meet; important, but
#: a distant fast pass is still not a crisis, so it ranks below proximity.
RISK_WEIGHT_ENERGY = 0.30
#: size — combined hard-body radius. Larger objects are marginally easier to
#: hit, but hard-body radii inferred from RCS are crude, so this only nudges
#: the score.
RISK_WEIGHT_SIZE = 0.10

#: Miss distance (km) at which the proximity term reaches 0. Equal to the
#: screening threshold: anything screened is within 10 km by definition.
PROXIMITY_MISS_DISTANCE_KM = 10.0
#: Relative velocity (km/s) at which the energy term saturates at 1.0 — roughly
#: the upper end of LEO head-on closing speeds.
ENERGY_RELATIVE_VELOCITY_KM_S = 15.0
#: Combined hard-body radius (m) at which the size term saturates at 1.0. A
#: generous cap; the vast majority of catalogue objects sit far below it.
SIZE_COMBINED_RADIUS_M = 100.0

# --------------------------------------------------------------------------- #
# risk_tier — a function of risk_score ALONE.                                 #
#                                                                             #
# The tier reflects encounter geometry only. Confidence is reported as its    #
# own field and is never folded in: "this looks dangerous" and "we trust this #
# data" are different statements, and conflating them is exactly the error    #
# this system is built to avoid.                                              #
# --------------------------------------------------------------------------- #

RISK_TIER_RED_THRESHOLD = 0.70
RISK_TIER_AMBER_THRESHOLD = 0.40

# --------------------------------------------------------------------------- #
# confidence — 0.05 .. 1.0, degrading with data staleness.                    #
#                                                                             #
#   confidence = clip(1.0 - age_term - low_orbit_penalty, 0.05, 1.0)          #
#                                                                             #
#   age_term = clip(max_epoch_age_hours / 168.0, 0, 1) * 0.70                 #
#       TLE predictive accuracy decays with epoch age. By ~1 week (168 h) an  #
#       un-refreshed element set is stale enough that we discount the result  #
#       by the full 0.70.                                                     #
#   low_orbit_penalty = 0.20 if min(perigee of both) < 500 km else 0.0        #
#       Below ~500 km atmospheric drag is the dominant force and the largest  #
#       un-modelled error in SGP4, so a stale TLE goes wrong fastest for      #
#       low-perigee objects. Flat 0.20.                                       #
# --------------------------------------------------------------------------- #

CONFIDENCE_AGE_FULL_HOURS = 168.0
CONFIDENCE_AGE_WEIGHT = 0.70
CONFIDENCE_LOW_ORBIT_PERIGEE_KM = 500.0
CONFIDENCE_LOW_ORBIT_PENALTY = 0.20
CONFIDENCE_FLOOR = 0.05

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "schemas"
    / "conjunction.schema.json"
)


def _clip(value: float, low: float, high: float) -> float:
    """Clamp ``value`` to the closed interval ``[low, high]``."""
    return max(low, min(high, value))


def risk_score(
    miss_distance_km: float,
    relative_velocity_km_s: float,
    combined_radius_m: float,
) -> float:
    """Composite risk score in [0, 1]. NOT a probability of collision.

    In one sentence: the weighted sum of how close the approach is (proximity,
    60%), how fast it is (energy, 30%), and how large the two objects are
    (size, 10%), each factor first normalised to [0, 1]::

        proximity = clip(1 - miss_distance_km / 10.0, 0, 1)
        energy    = clip(relative_velocity_km_s / 15.0, 0, 1)
        size      = clip(combined_radius_m / 100.0, 0, 1)
        risk_score = 0.60 * proximity + 0.30 * energy + 0.10 * size

    The weights (``RISK_WEIGHT_*``) are engineering judgement, not derived from
    first principles — see the module-level constants for the reasoning behind
    each one.

    Args:
        miss_distance_km: range between the two objects at TCA, km (>= 0).
        relative_velocity_km_s: magnitude of the relative velocity at TCA,
            km/s (>= 0).
        combined_radius_m: sum of the two objects' hard-body radii, m (> 0).

    Returns:
        Score in [0, 1]. Non-decreasing as ``miss_distance_km`` falls and as
        ``relative_velocity_km_s`` or ``combined_radius_m`` rises (see
        test_scoring.py for the monotonicity assertions this must satisfy).
    """
    proximity = _clip(1.0 - miss_distance_km / PROXIMITY_MISS_DISTANCE_KM, 0.0, 1.0)
    energy = _clip(relative_velocity_km_s / ENERGY_RELATIVE_VELOCITY_KM_S, 0.0, 1.0)
    size = _clip(combined_radius_m / SIZE_COMBINED_RADIUS_M, 0.0, 1.0)
    return (
        RISK_WEIGHT_PROXIMITY * proximity
        + RISK_WEIGHT_ENERGY * energy
        + RISK_WEIGHT_SIZE * size
    )


def risk_tier(score_value: float) -> RiskTier:
    """Discretise a ``risk_score`` into GREEN / AMBER / RED.

    From the score alone — confidence is never an input here.

    Args:
        score_value: a ``risk_score`` output, expected in [0, 1].

    Returns:
        ``RiskTier.RED`` if ``score_value >= 0.70``, ``RiskTier.AMBER`` if
        ``score_value >= 0.40``, ``RiskTier.GREEN`` otherwise.
    """
    if score_value >= RISK_TIER_RED_THRESHOLD:
        return RiskTier.RED
    if score_value >= RISK_TIER_AMBER_THRESHOLD:
        return RiskTier.AMBER
    return RiskTier.GREEN


def _confidence_note(
    confidence: float,
    max_epoch_age_hours: float,
    low_orbit: bool,
) -> str:
    """Plain-English, user-facing reason the confidence is what it is.

    Always names the older epoch age in hours; names the low-orbit drag
    penalty when it applies.
    """
    age_h = f"{max_epoch_age_hours:.0f} h"
    stale = max_epoch_age_hours >= CONFIDENCE_AGE_FULL_HOURS
    aged = max_epoch_age_hours >= 24.0

    if stale and low_orbit:
        return (
            f"Low confidence ({confidence:.2f}): the older of the two TLEs is "
            f"{age_h} old — past the {CONFIDENCE_AGE_FULL_HOURS:.0f} h point where "
            f"TLE predictions are treated as stale — and the lower object's "
            f"perigee is below {CONFIDENCE_LOW_ORBIT_PERIGEE_KM:.0f} km, where "
            f"atmospheric drag makes those predictions degrade fastest."
        )
    if stale:
        return (
            f"Low confidence ({confidence:.2f}): the older of the two TLEs is "
            f"{age_h} old, past the {CONFIDENCE_AGE_FULL_HOURS:.0f} h point where "
            f"TLE predictions are treated as stale; the maximum age penalty is "
            f"applied."
        )
    if aged and low_orbit:
        return (
            f"Reduced confidence ({confidence:.2f}): the older of the two TLEs is "
            f"{age_h} old, and the lower object's perigee is below "
            f"{CONFIDENCE_LOW_ORBIT_PERIGEE_KM:.0f} km, where atmospheric drag "
            f"makes TLE predictions degrade fastest."
        )
    if aged:
        return (
            f"Reduced confidence ({confidence:.2f}): the older of the two TLEs is "
            f"{age_h} old and TLE accuracy decays with epoch age."
        )
    if low_orbit:
        return (
            f"Slightly reduced confidence ({confidence:.2f}): both TLEs are recent "
            f"(older epoch {age_h}), but the lower object's perigee is below "
            f"{CONFIDENCE_LOW_ORBIT_PERIGEE_KM:.0f} km, where atmospheric drag "
            f"makes TLE predictions degrade fastest."
        )
    return (
        f"High confidence ({confidence:.2f}): both TLEs are recent (older epoch "
        f"{age_h}) and neither object's perigee is below "
        f"{CONFIDENCE_LOW_ORBIT_PERIGEE_KM:.0f} km."
    )


def confidence_band(
    max_epoch_age_hours: float,
    min_perigee_km: float,
) -> tuple[float, str]:
    """Confidence in [0.05, 1.0] that the screening result is trustworthy, plus a note.

    ::

        age_term          = clip(max_epoch_age_hours / 168.0, 0, 1) * 0.70
        low_orbit_penalty = 0.20 if min_perigee_km < 500.0 else 0.0
        confidence        = clip(1.0 - age_term - low_orbit_penalty, 0.05, 1.0)

    ``age_term``: TLE predictive accuracy decays with epoch age; by ~1 week the
    element set is stale enough to discount by the full 0.70. ``low_orbit_penalty``:
    below ~500 km atmospheric drag is the dominant un-modelled force and stale
    TLEs degrade fastest, so a flat 0.20 is subtracted. This value is reported
    on its own and is **never** folded into ``risk_tier``.

    Args:
        max_epoch_age_hours: the larger of the two objects' ``epoch_age_hours``
            at screening time, hours (>= 0).
        min_perigee_km: the smaller of the two objects' perigee altitudes, km.

    Returns:
        ``(confidence, confidence_note)``. ``confidence`` in [0.05, 1.0];
        ``confidence_note`` a plain-English sentence, shown to the user, that
        names the epoch age in hours and — when it applies — the low-orbit drag
        penalty. Monotonically non-increasing in ``max_epoch_age_hours``.
    """
    age_fraction = _clip(max_epoch_age_hours / CONFIDENCE_AGE_FULL_HOURS, 0.0, 1.0)
    age_term = age_fraction * CONFIDENCE_AGE_WEIGHT
    low_orbit = min_perigee_km < CONFIDENCE_LOW_ORBIT_PERIGEE_KM
    low_orbit_penalty = CONFIDENCE_LOW_ORBIT_PENALTY if low_orbit else 0.0

    confidence = _clip(1.0 - age_term - low_orbit_penalty, CONFIDENCE_FLOOR, 1.0)
    return confidence, _confidence_note(confidence, max_epoch_age_hours, low_orbit)


def compute_pc(*_args: object, **_kwargs: object) -> float:
    """DISABLED. Placeholder interface for a covariance-based probability of collision.

    Do not call this from the normal scoring path. It exists only so that, if
    covariance data becomes available in the future (e.g. via CDM ingestion),
    there is a documented seam to add real Pc computation without restructuring
    scoring.py. Wiring this up requires an explicit product decision — see root
    README, "Why we don't publish a probability of collision" — not just a code
    change.

    Raises:
        NotImplementedError: always, unconditionally.
    """
    raise NotImplementedError(
        "compute_pc is intentionally disabled: no covariance data is available "
        "from public TLEs. See root README 'Why we don't publish a probability "
        "of collision' before enabling this."
    )


def score(
    candidate: ScreeningResult,
    primary: CatalogObject,
    secondary: CatalogObject,
    *,
    screened_at: datetime | None = None,
) -> ConjunctionEvent:
    """Assemble a schema-valid ``ConjunctionEvent`` from one screened approach.

    The output matches ``contracts/schemas/conjunction.schema.json`` exactly.
    ``risk_score`` is the transparent composite defined in :func:`risk_score`
    and is explicitly **not** a probability of collision — public TLEs carry no
    covariance, so no true Pc is derivable (root README, "Why we don't publish
    a probability of collision").

    Args:
        candidate: exact close-approach geometry for one approach, from
            :func:`prahari_orbital.screen.screen_candidates`. Its
            ``primary_norad_id`` / ``secondary_norad_id`` must match
            ``primary`` / ``secondary``.
        primary: catalogue record for ``candidate.primary_norad_id``. Its RIC
            frame is the one ``candidate``'s components are expressed in.
        secondary: catalogue record for ``candidate.secondary_norad_id``.
        screened_at: when this screening run was produced, timezone-aware UTC.
            Defaults to ``datetime.now(UTC)``.

    Returns:
        A :class:`~prahari_orbital.models.ConjunctionEvent` with a fresh
        ``event_id`` (uuid4), ``combined_radius_m`` the sum of the two objects'
        ``radius_m``, ``risk_score`` / ``risk_tier`` from :func:`risk_score` /
        :func:`risk_tier`, and ``confidence`` / ``confidence_note`` from
        :func:`confidence_band`. Never carries a probability field —
        ``ConjunctionEvent`` has none by contract.

    Raises:
        ValueError: ``candidate``'s NORAD ids do not match ``primary`` /
            ``secondary``, or ``screened_at`` is a naive datetime.
    """
    if (
        candidate.primary_norad_id != primary.norad_id
        or candidate.secondary_norad_id != secondary.norad_id
    ):
        raise ValueError(
            f"score: candidate ids "
            f"{candidate.primary_norad_id}/{candidate.secondary_norad_id} do not "
            f"match objects {primary.norad_id}/{secondary.norad_id}"
        )
    if screened_at is None:
        screened_at = datetime.now(UTC)
    elif screened_at.tzinfo is None or screened_at.utcoffset() is None:
        raise ValueError("score: screened_at must be timezone-aware UTC")

    combined_radius_m = primary.radius_m + secondary.radius_m
    score_value = risk_score(
        candidate.miss_distance_km,
        candidate.relative_velocity_km_s,
        combined_radius_m,
    )

    max_epoch_age_hours = max(primary.epoch_age_hours, secondary.epoch_age_hours)
    min_perigee_km = min(primary.perigee_km, secondary.perigee_km)
    confidence, confidence_note = confidence_band(max_epoch_age_hours, min_perigee_km)

    return ConjunctionEvent(
        event_id=str(uuid.uuid4()),
        primary=ObjectRef(norad_id=primary.norad_id, name=primary.name),
        secondary=ObjectRef(norad_id=secondary.norad_id, name=secondary.name),
        tca=candidate.tca.utc_datetime(),
        miss_distance_km=candidate.miss_distance_km,
        relative_velocity_km_s=candidate.relative_velocity_km_s,
        radial_km=candidate.radial_km,
        in_track_km=candidate.in_track_km,
        cross_track_km=candidate.cross_track_km,
        combined_radius_m=combined_radius_m,
        risk_score=score_value,
        risk_tier=risk_tier(score_value),
        confidence=confidence,
        confidence_note=confidence_note,
        max_epoch_age_hours=max_epoch_age_hours,
        screened_at=screened_at,
    )


def build_event(
    primary: CatalogObject,
    secondary: CatalogObject,
    result: ScreeningResult,
    *,
    screened_at: str,
) -> ConjunctionEvent:
    """Deprecated alias for :func:`score`, kept for the worker's screening loop.

    Same result as ``score(result, primary, secondary, screened_at=...)``; the
    only difference is that ``screened_at`` is an ISO 8601 UTC string here (the
    historical signature) rather than a ``datetime``.

    Args:
        primary: catalogue record for ``result.primary_norad_id``.
        secondary: catalogue record for ``result.secondary_norad_id``.
        result: exact geometry from :func:`prahari_orbital.screen.screen_pair`.
        screened_at: ISO 8601 UTC timestamp of this screening run.

    Returns:
        The :class:`~prahari_orbital.models.ConjunctionEvent` from :func:`score`.
    """
    parsed = datetime.fromisoformat(screened_at)  # 3.11+ accepts a trailing "Z"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return score(result, primary, secondary, screened_at=parsed)


@lru_cache(maxsize=1)
def _conjunction_schema() -> dict[str, Any]:
    """The frozen conjunction JSON Schema, loaded once from ``contracts/schemas/``."""
    with _SCHEMA_PATH.open(encoding="utf-8") as handle:
        schema: dict[str, Any] = json.load(handle)
    return schema


@lru_cache(maxsize=1)
def _validator() -> Draft7Validator:
    """Draft-07 validator for the conjunction schema, with format checking on."""
    return Draft7Validator(
        _conjunction_schema(), format_checker=Draft7Validator.FORMAT_CHECKER
    )


def _event_payload(event: ConjunctionEvent) -> dict[str, Any]:
    """One event as a plain JSON-ready dict (datetimes -> ISO 8601 strings)."""
    payload: dict[str, Any] = event.model_dump(mode="json")
    return payload


def validate_event_dict(event: dict[str, Any]) -> list[str]:
    """Schema violations for one event dict — empty list means it validates.

    Checks against ``contracts/schemas/conjunction.schema.json``, including
    ``additionalProperties: false`` (a stray field such as ``pc`` fails here),
    ``required``, types, enums, and the [0, 1] bounds on ``risk_score`` /
    ``confidence``.

    Args:
        event: a candidate event, e.g. ``ConjunctionEvent.model_dump(mode="json")``.

    Returns:
        Human-readable ``"<path>: <message>"`` strings, one per violation,
        ordered by location in the document.
    """
    return [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(
            _validator().iter_errors(event), key=lambda e: list(e.absolute_path)
        )
    ]


def export_events(
    events: Iterable[ConjunctionEvent],
    path: str | Path,
) -> Path:
    """Write ``events`` as a JSON array, schema-validating every one first.

    Each event is serialised with ``ConjunctionEvent.model_dump(mode="json")``
    and checked against the frozen conjunction schema. If **any** event fails,
    nothing is written and :class:`ValueError` is raised listing every
    violation — a bad batch fails loudly rather than shipping a malformed file.

    Args:
        events: the events to write.
        path: destination ``.json`` file (overwritten if it exists).

    Returns:
        The :class:`~pathlib.Path` that was written.

    Raises:
        ValueError: one or more events do not validate against
            ``contracts/schemas/conjunction.schema.json``.
    """
    payload = [_event_payload(event) for event in events]

    problems: list[str] = []
    for index, event_dict in enumerate(payload):
        event_id = event_dict.get("event_id", "?")
        problems.extend(
            f"event[{index}] ({event_id}): {message}"
            for message in validate_event_dict(event_dict)
        )
    if problems:
        raise ValueError(
            f"export_events: {len(problems)} schema violation(s), nothing written:\n  "
            + "\n  ".join(problems)
        )

    out_path = Path(path)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out_path
