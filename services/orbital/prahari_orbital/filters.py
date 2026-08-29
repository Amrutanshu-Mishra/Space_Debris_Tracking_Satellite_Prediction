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

import numpy as np

from prahari_orbital.frames import StateVector
from prahari_orbital.models import CatalogObject

DEFAULT_THRESHOLD_KM = 25.0

#: Any pair whose minimum separation over the propagation window falls below
#: this is a candidate conjunction event (see services/orbital/CLAUDE.md,
#: "Screening and scoring"). apogee_perigee_filter's pad_km must stay well
#: above it.
SCREENING_THRESHOLD_KM = 10.0


@dataclass(frozen=True)
class CandidatePair:
    """One pair surviving the coarse filter, carried forward to screen.py."""

    primary_norad_id: int
    secondary_norad_id: int
    min_separation_km: float
    """Minimum sampled separation across the coarse time grid, km. A lower
    bound used for prioritisation, NOT the true miss distance — screen.py
    computes the true miss distance via fine re-propagation and root-finding."""


@dataclass(frozen=True)
class ApogeePerigeeFilterResult:
    """Survivors of :func:`apogee_perigee_filter` plus its reduction stats.

    Attributes:
        pairs: surviving candidate pairs as ``(low_norad_id, high_norad_id)``
            tuples (ids ascending within each tuple, list sorted ascending).
            Every pair whose radial altitude bands overlap within ``pad_km``;
            everything else has been proven unable to conjunct and dropped.
        total_pairs: ``n * (n - 1) // 2`` — the unfiltered pair count.
        surviving_pairs: ``len(pairs)``.
        survival_ratio: ``surviving_pairs / total_pairs`` (``0.0`` when
            ``total_pairs == 0``). The fraction kept; ``1 - survival_ratio``
            is the fraction discarded.
    """

    pairs: list[tuple[int, int]]
    total_pairs: int
    surviving_pairs: int
    survival_ratio: float


def apogee_perigee_filter(
    objects: list[CatalogObject],
    pad_km: float = 100.0,
) -> ApogeePerigeeFilterResult:
    """Drop object pairs whose radial altitude bands cannot overlap.

    RULE. A pair is discarded when one object's perigee clears the other's
    apogee by more than ``pad_km``::

        perigee_A - apogee_B > pad_km   or   perigee_B - apogee_A > pad_km

    Orbits separated like that never bring the two objects within the
    screening threshold, whatever their phasing or node geometry, so the
    pair can be dropped without ever propagating it. Every other pair
    survives.

    The comparison uses ``perigee_km`` / ``apogee_km`` straight off each
    :class:`~prahari_orbital.models.CatalogObject` — spherical *mean-element*
    altitudes derived from the TLE's mean motion and eccentricity (see
    :func:`prahari_orbital.ingest.build_catalog_objects`). Propagated
    positions are deliberately not consulted: this stage runs before any
    propagation.

    Why ``pad_km`` defaults to 100 km. The pad has to absorb every way the
    true radial separation can come out smaller than the mean-element band
    gap implies:

    * the 10 km screening threshold itself — two objects 10 km apart are
      already a candidate event, so the gap must be shrunk by at least that;
    * mean vs. osculating radius — ``perigee_km`` / ``apogee_km`` are from
      *mean* elements, but the instantaneous geocentric radius breathes
      around them by ~10-20 km per revolution under J2;
    * element/propagation drift over the 72 h coarse-screening window — the
      along- and cross-track error of a day-old TLE grows to a few tens of
      km by 72 h, and some of that projects onto the radial direction.

    100 km comfortably dominates the sum of those (~10 + ~20 + ~40 km) while
    still discarding the large majority of catalogue pairs (any LEO object
    against anything in MEO/GEO, most pairs that cross altitude regimes).
    The filter is intentionally conservative: keeping a pair that later
    screens clean costs one cheap propagation downstream, whereas dropping a
    pair that was real is a silent missed warning. When the pad and the gap
    are close, the pair is kept.

    Args:
        objects: catalogue objects to pair up. Fewer than two ⇒ no pairs.
        pad_km: slack added to the apogee/perigee comparison, in kilometres.
            Larger ⇒ more conservative (more pairs kept). A negative value
            would make the filter *aggressive* and is almost certainly a
            mistake, but is not rejected here.

    Returns:
        :class:`ApogeePerigeeFilterResult` — ``pairs`` holds the surviving
        ``(low_id, high_id)`` NORAD-id tuples; the other fields are the
        reduction statistics.

    Units/frame: ``pad_km`` and the objects' perigee/apogee are kilometres
        above a spherical Earth (mean-element altitudes). Output is integer
        NORAD-id pairs — dimensionless, no coordinate frame involved.
    """
    n = len(objects)
    total_pairs = n * (n - 1) // 2
    if total_pairs == 0:
        return ApogeePerigeeFilterResult(
            pairs=[], total_pairs=0, surviving_pairs=0, survival_ratio=0.0
        )

    norad_ids = np.fromiter((o.norad_id for o in objects), dtype=np.int64, count=n)
    perigee_km = np.fromiter((o.perigee_km for o in objects), dtype=np.float64, count=n)
    apogee_km = np.fromiter((o.apogee_km for o in objects), dtype=np.float64, count=n)

    # Every unordered pair once, as two index arrays — no Python loop over
    # objects. Intermediate size is O(n^2); fine for prototype catalogue
    # slices. Scaling to the full ~30k feed is the sorted-sweep prefilter's
    # job (apogee_perigee_prefilter), not this function's.
    i_idx, j_idx = np.triu_indices(n, k=1)

    clears_ij = perigee_km[i_idx] - apogee_km[j_idx] > pad_km
    clears_ji = perigee_km[j_idx] - apogee_km[i_idx] > pad_km
    keep = ~(clears_ij | clears_ji)

    id_a = norad_ids[i_idx[keep]]
    id_b = norad_ids[j_idx[keep]]
    lo = np.minimum(id_a, id_b).tolist()
    hi = np.maximum(id_a, id_b).tolist()
    pairs: list[tuple[int, int]] = sorted((int(a), int(b)) for a, b in zip(lo, hi))

    return ApogeePerigeeFilterResult(
        pairs=pairs,
        total_pairs=total_pairs,
        surviving_pairs=len(pairs),
        survival_ratio=len(pairs) / total_pairs,
    )


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
