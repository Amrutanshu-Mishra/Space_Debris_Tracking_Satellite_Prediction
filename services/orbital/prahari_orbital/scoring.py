"""Risk score + confidence: turns a ScreeningResult into a ConjunctionEvent.

NON-NEGOTIABLE DESIGN CONSTRAINT: this module never computes or emits a
probability of collision. Public TLEs carry no covariance, so a true Pc is
not statistically derivable from this data — see root README, "Why we
don't publish a probability of collision". `risk_score` is a composite,
clearly-labelled heuristic; `confidence` separately captures how much to
trust it given TLE staleness. `compute_pc` below is a documented, disabled
stub for the day covariance data is available (e.g. CDM ingestion) — it
must stay unreachable from the normal scoring path.
"""

from __future__ import annotations

from prahari_orbital.models import CatalogObject, ConjunctionEvent, RiskTier
from prahari_orbital.screen import ScreeningResult

# Weights for the composite risk_score. Tuned, not derived — document any
# change here and in docs/architecture.md, a judge may ask for the rationale.
MISS_DISTANCE_WEIGHT = 0.6
RELATIVE_VELOCITY_WEIGHT = 0.4
MISS_DISTANCE_SATURATION_KM = 5.0
"""Miss distances >= this contribute ~0 to risk_score's distance term."""
RELATIVE_VELOCITY_SATURATION_KM_S = 15.0
"""Relative velocities >= this saturate risk_score's velocity term at 1.0."""

RISK_TIER_AMBER_THRESHOLD = 0.35
RISK_TIER_RED_THRESHOLD = 0.70

CONFIDENCE_HALFLIFE_HOURS = 240.0
"""Epoch age at which confidence decays to ~ minimum floor; see confidence_band."""
CONFIDENCE_FLOOR = 0.15
LOW_PERIGEE_THRESHOLD_KM = 500.0
"""Below this altitude, atmospheric drag dominates TLE staleness error."""


def risk_score(miss_distance_km: float, relative_velocity_km_s: float) -> float:
    """Composite risk score in [0, 1] from miss distance and relative velocity.

    NOT a probability of collision. Combines a distance term (closer = higher,
    saturating at MISS_DISTANCE_SATURATION_KM) and a velocity term (faster =
    higher, saturating at RELATIVE_VELOCITY_SATURATION_KM_S), weighted by
    MISS_DISTANCE_WEIGHT / RELATIVE_VELOCITY_WEIGHT.

    Args:
        miss_distance_km: true miss distance at TCA, km.
        relative_velocity_km_s: relative speed at TCA, km/s.

    Returns:
        Score in [0, 1], monotonically decreasing in miss_distance_km and
        increasing in relative_velocity_km_s (see test_scoring.py for the
        monotonicity assertions this must satisfy).
    """
    raise NotImplementedError(
        "TODO(screening-scoring): dist_term = clip(1 - miss/SAT, 0, 1); "
        "vel_term = clip(v/SAT, 0, 1); weighted sum"
    )


def risk_tier(score: float) -> RiskTier:
    """Discretise a risk_score into GREEN/AMBER/RED via the module thresholds.

    Args:
        score: risk_score output, expected in [0, 1].

    Returns:
        RiskTier.RED if score >= RISK_TIER_RED_THRESHOLD,
        RiskTier.AMBER if score >= RISK_TIER_AMBER_THRESHOLD,
        RiskTier.GREEN otherwise.
    """
    raise NotImplementedError("TODO(screening-scoring): threshold comparison, see module constants")


def confidence_band(
    primary: CatalogObject,
    secondary: CatalogObject,
) -> tuple[float, str]:
    """Confidence in [0, 1] that the screening result is trustworthy, plus a note.

    Decays with the older of the two objects' epoch_age_hours (exponential
    decay toward CONFIDENCE_FLOOR with half-life CONFIDENCE_HALFLIFE_HOURS),
    further reduced when either object's perigee is below
    LOW_PERIGEE_THRESHOLD_KM (drag makes stale TLEs wrong faster there).

    Args:
        primary: first object.
        secondary: second object.

    Returns:
        (confidence, confidence_note) — confidence in [0, 1]; confidence_note
        is a human-readable sentence naming which object's epoch is stale
        and/or whether low-perigee drag uncertainty applies, or a clean-bill
        sentence if neither condition triggers. Matches conjunction.schema.json's
        confidence_note field verbatim in tone/format.
    """
    raise NotImplementedError("TODO(screening-scoring): exponential decay on max(epoch_age_hours) + perigee check")


def compute_pc(*_args: object, **_kwargs: object) -> float:
    """DISABLED. Placeholder interface for a covariance-based probability of collision.

    Do not call this from the normal scoring path. It exists only so that,
    if covariance data becomes available in the future (e.g. via CDM
    ingestion), there is a documented seam to add real Pc computation without
    restructuring scoring.py. Wiring this up requires an explicit product
    decision — see root README, "Why we don't publish a probability of
    collision" — not just a code change.

    Raises:
        NotImplementedError: always, unconditionally.
    """
    raise NotImplementedError(
        "compute_pc is intentionally disabled: no covariance data is available from public TLEs. "
        "See root README 'Why we don't publish a probability of collision' before enabling this."
    )


def build_event(
    primary: CatalogObject,
    secondary: CatalogObject,
    result: ScreeningResult,
    *,
    screened_at: str,
) -> ConjunctionEvent:
    """Assemble a ConjunctionEvent from a ScreeningResult plus the two objects.

    Args:
        primary: first object (matches result.primary_norad_id).
        secondary: second object (matches result.secondary_norad_id).
        result: exact geometry from screen.screen_pair.
        screened_at: ISO 8601 UTC timestamp of this screening run.

    Returns:
        ConjunctionEvent with a fresh event_id (uuid4), risk_score/risk_tier
        from risk_score()/risk_tier(), confidence/confidence_note from
        confidence_band(). Never sets a probability field — ConjunctionEvent
        has none by contract (contracts/schemas/conjunction.schema.json).
    """
    raise NotImplementedError("TODO(screening-scoring): compose ObjectRef x2, risk_score, risk_tier, confidence_band, uuid4()")
