"""Coarse filtering: the crux of the pipeline.

30,000 objects means ~450 million pairs. Brute-force fine screening every
pair is impossible on an 8-core laptop. This module must prune >99.99% of
pairs before anything reaches screen.py's 1-second-resolution re-propagation.

Two-stage approach:
    1. Analytic apogee/perigee prefilter (cheap, O(N log N) via sorting) —
       Hoots, Crawford & Roehrich (1984), "Application of the Method of
       Averages to Analytical Satellite Theory Applied to the Problem of
       Predicting Close Approaches", Celestial Mechanics 33(2), 143-158.
       If object A's perigee exceeds object B's apogee by more than a
       threshold margin, their orbits can never intersect within the
       screening window — discard the pair without ever propagating it.
    2. Spatial KD-tree filter on propagated positions at each coarse time
       step — objects farther apart than COARSE_FILTER_THRESHOLD_KM at every
       sampled instant cannot have a close approach between samples (given a
       conservative bound on relative velocity), so they're discarded too.

Anything that survives both stages goes to screen.py for fine screening.
"""

from __future__ import annotations

from dataclasses import dataclass

from prahari_orbital.frames import StateVector
from prahari_orbital.models import CatalogObject

DEFAULT_THRESHOLD_KM = 25.0


@dataclass(frozen=True)
class CandidatePair:
    """One pair surviving the coarse filter, carried forward to screen.py."""

    primary_norad_id: int
    secondary_norad_id: int
    min_separation_km: float
    """Minimum sampled separation across the coarse time grid, km. A lower
    bound used for prioritisation, NOT the true miss distance — screen.py
    computes the true miss distance via fine re-propagation and root-finding."""


def apogee_perigee_prefilter(
    objects: list[CatalogObject],
    *,
    margin_km: float = DEFAULT_THRESHOLD_KM,
) -> list[tuple[int, int]]:
    """Discard pairs whose altitude bands cannot possibly overlap.

    Sorts objects by perigee, then for each object sweeps forward while the
    next object's perigee is within [this object's apogee + margin]. This
    is the Hoots/Crawford/Roehrich altitude-band test — see module docstring
    for the citation. O(N log N) for the sort, ~O(N) for the sweep in the
    typical case (LEO altitude bands are not uniformly dense, so the sweep
    can degrade toward O(N^2) in pathological clustering; acceptable at
    N=30k on an 8-core laptop, revisit only if profiling says otherwise).

    Args:
        objects: full catalogue.
        margin_km: extra slack added to the apogee/perigee comparison to
            account for TLE mean-element uncertainty. Same units and same
            default as COARSE_FILTER_THRESHOLD_KM.

    Returns:
        List of (norad_id, norad_id) pairs, primary < secondary by norad_id,
        whose altitude bands overlap within margin_km and therefore need the
        spatial KD-tree pass.
    """
    raise NotImplementedError("TODO(screening-scoring): sort by perigee_km, sweep with a max-heap of open apogees")


def orbit_path_filter(
    objects_by_id: dict[int, CatalogObject],
    candidate_pairs: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Discard pairs whose orbital planes/paths cannot geometrically intersect.

    Cheaper than full propagation: compares orbit-plane geometry (inclination,
    RAAN) to bound the minimum possible separation between the two orbital
    paths, independent of where each object is along its path at any given
    time. A second Hoots/Crawford/Roehrich-style analytic test, applied after
    apogee_perigee_prefilter to shrink the set before the spatial KD-tree pass.

    Args:
        objects_by_id: full catalogue, keyed by norad_id.
        candidate_pairs: survivors of apogee_perigee_prefilter.

    Returns:
        Further-pruned list of (norad_id, norad_id) pairs.
    """
    raise NotImplementedError("TODO(screening-scoring): orbital-plane minimum-distance bound, see HCR84 sec. 3")


def spatial_kdtree_filter(
    states: dict[int, StateVector],
    candidate_pairs: list[tuple[int, int]],
    *,
    threshold_km: float = DEFAULT_THRESHOLD_KM,
) -> list[CandidatePair]:
    """Final coarse-filter stage: KD-tree nearest-neighbour query per time step.

    For each sampled instant in the coarse time grid, builds a KD-tree over
    all propagated positions and queries, per candidate pair, whether the two
    objects are ever within threshold_km of each other. This catches close
    approaches that the analytic filters' conservative bounds let through,
    at the cost of actually needing propagated positions (unlike the two
    filters above, which only need mean elements).

    Args:
        states: output of propagate.propagate_many — norad_id -> StateVector
            (frame "GCRS", shape (N, 3)), N = coarse time-grid length.
        candidate_pairs: survivors of orbit_path_filter.
        threshold_km: any pair never within this distance at any sampled
            instant is discarded. Must be >= the true miss-distance cutoff
            used downstream, since the fine screen only sees what's passed here.

    Returns:
        CandidatePair list, min_separation_km populated from the coarse
        sampling (a lower bound, not the true TCA miss distance).
    """
    raise NotImplementedError(
        "TODO(screening-scoring): scipy.spatial.cKDTree per time step, query_pairs / query_ball_tree"
    )


def coarse_filter(
    objects: list[CatalogObject],
    states: dict[int, StateVector],
    *,
    threshold_km: float = DEFAULT_THRESHOLD_KM,
) -> list[CandidatePair]:
    """Run the full three-stage coarse filter, apogee/perigee -> orbit-path -> KD-tree.

    This is the only entry point screen.py should call; the three functions
    above exist separately for unit testing (test_filters.py must assert
    each stage never discards a synthetic true positive on its own).

    Args:
        objects: full catalogue.
        states: propagated positions from propagate.propagate_many, coarse
            time grid (e.g. 60 s step over 72 h).
        threshold_km: passed through to spatial_kdtree_filter.

    Returns:
        CandidatePair list ready for screen.py's fine re-propagation.
        Must prune the input pair count (~N*(N-1)/2) by >99.99% — this is
        the funnel number reported in CatalogStatus.pairs_fine_screened.
    """
    raise NotImplementedError("TODO(screening-scoring): compose apogee_perigee_prefilter -> orbit_path_filter -> spatial_kdtree_filter")
