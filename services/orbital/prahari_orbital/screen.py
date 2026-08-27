"""Fine screening: exact TCA and miss distance for coarse-filter survivors.

For each CandidatePair from filters.coarse_filter, re-propagates both
objects at 1-second resolution around the coarse approach and root-finds
the true time of closest approach (TCA) — the instant the relative
range-rate (d/dt of separation distance) crosses zero — via Brent's method.
Produces the raw geometry that scoring.py turns into a ConjunctionEvent.
"""

from __future__ import annotations

from dataclasses import dataclass

from skyfield.api import Time

from prahari_orbital.filters import CandidatePair
from prahari_orbital.models import CatalogObject

FINE_STEP_SECONDS = 1.0


@dataclass(frozen=True)
class ScreeningResult:
    """Exact close-approach geometry for one pair, ready for scoring.py.

    Units: tca as Skyfield Time; distances km; velocity km/s. radial/in_track/
    cross_track are the RTN decomposition of the miss vector (frames.rtn_basis),
    same sign convention as conjunction.schema.json.
    """

    primary_norad_id: int
    secondary_norad_id: int
    tca: Time
    miss_distance_km: float
    relative_velocity_km_s: float
    radial_km: float
    in_track_km: float
    cross_track_km: float


def range_rate(
    primary: CatalogObject,
    secondary: CatalogObject,
    t: Time,
) -> float:
    """Signed relative range-rate between two objects at instant t.

    d(range)/dt: negative while closing, positive while opening, zero at TCA.
    This is the function Brent's method root-finds over in find_tca.

    Args:
        primary: first object.
        secondary: second object.
        t: single Skyfield Time instant.

    Returns:
        Range rate, km/s. Negative = closing.
    """
    raise NotImplementedError(
        "TODO(screening-scoring): propagate both at t, "
        "d = pos_b - pos_a, dv = vel_b - vel_a, return dot(d, dv) / norm(d)"
    )


def find_tca(
    primary: CatalogObject,
    secondary: CatalogObject,
    *,
    search_start: Time,
    search_end: Time,
) -> Time:
    """Root-find the time of closest approach via Brent's method on range_rate.

    Args:
        primary: first object.
        secondary: second object.
        search_start: lower bound of the search bracket — must have
            range_rate < 0 (closing) for Brent to bracket a root; typically
            the coarse time-grid sample immediately before the coarse minimum.
        search_end: upper bound of the search bracket — must have
            range_rate > 0 (opening); typically the sample immediately after.

    Returns:
        Skyfield Time at which range_rate crosses zero (the TCA).

    Raises:
        ValueError: if range_rate does not change sign across the bracket
            (i.e. the coarse filter handed us a bad bracket — this is a bug
            in filters.py, not a data problem, and should not be swallowed).
    """
    raise NotImplementedError("TODO(screening-scoring): scipy.optimize.brentq(range_rate, search_start, search_end)")


def screen_pair(
    primary: CatalogObject,
    secondary: CatalogObject,
    candidate: CandidatePair,
    *,
    coarse_step_seconds: float,
) -> ScreeningResult:
    """Fine-screen a single coarse-filter survivor: find TCA, compute full geometry.

    Args:
        primary: first object.
        secondary: second object.
        candidate: coarse-filter output for this pair, used to bracket the
            search window for find_tca (search around the coarse-grid instant
            where min_separation_km was observed, +/- one coarse_step_seconds).
        coarse_step_seconds: the step size the coarse grid was sampled at,
            needed to reconstruct the search bracket around the coarse minimum.

    Returns:
        ScreeningResult with exact TCA, miss distance, relative velocity, and
        RTN-decomposed miss vector.
    """
    raise NotImplementedError("TODO(screening-scoring): find_tca then propagate both at TCA, project via frames.rtn_basis")


def screen_candidates(
    objects_by_id: dict[int, CatalogObject],
    candidates: list[CandidatePair],
    *,
    coarse_step_seconds: float,
) -> list[ScreeningResult]:
    """Fine-screen every coarse-filter survivor.

    Args:
        objects_by_id: full catalogue, keyed by norad_id.
        candidates: output of filters.coarse_filter.
        coarse_step_seconds: passed through to screen_pair.

    Returns:
        One ScreeningResult per candidate. Candidates whose bracket does not
        actually contain a sign change (see find_tca Raises) are logged and
        skipped, not fatal to the batch.
    """
    raise NotImplementedError("TODO(screening-scoring): loop screen_pair over candidates, catch+log ValueError per pair")
