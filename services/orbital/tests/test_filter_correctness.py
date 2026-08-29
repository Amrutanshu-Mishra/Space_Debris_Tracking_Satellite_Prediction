"""Neither the coarse filter nor the fine screen may discard a real approach.

Two independent brute-force checks, both against an external reference, never
against our own output at the same resolution:

1. :func:`test_filter_discards_nothing_real` — a false negative in
   :func:`apogee_perigee_filter` is silent and unrecoverable: a genuine close
   approach simply never reaches ``screen.py``. So this test trusts the
   filter's logic not at all: it runs the full O(N^2) brute force (every pair,
   minimum separation over a real 6-hour propagation) and the filtered path
   side by side and asserts they flag the same sub-10-km set.

2. :func:`test_three_pass_pipeline_finds_every_fine_grid_event` — ``screen.py``
   samples separation on a 60 s grid, and two objects closing fast move
   hundreds of km between samples, so a sub-10-km miss can read as sub-threshold
   at *no* sample. A 60-s-vs-60-s comparison is structurally blind to this. So
   the reference here is a **5 s** propagation: any pair below 10 km on the 5 s
   grid is a genuine event (the true minimum is only ever smaller), and the
   padded three-pass ``screen_candidates`` — still sampling at 60 s — must
   recover every one of them. In this fixture all such events are invisible at
   60 s, so this is exactly the class of miss check (1) cannot see.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from prahari_orbital.filters import (
    SCREENING_THRESHOLD_KM,
    CandidatePair,
    apogee_perigee_filter,
)
from prahari_orbital.ingest import build_catalog_objects, parse_tle_block, validate_tle_pair
from prahari_orbital.models import CatalogObject
from prahari_orbital.propagate import CatalogEphemeris, propagate_catalog
from prahari_orbital.screen import screen_candidates

CACHE_TLE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "cache"
    / "active_20260829T120000Z.tle"
)
NOW_UTC = "2026-08-29T12:00:00Z"
START = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
HOURS = 6
STEP_SECONDS = 60

#: Reference resolution for the fine-screen check. The screening pipeline
#: samples at ``STEP_SECONDS`` (60 s); this 5 s grid is the external truth it
#: is measured against — fine enough to expose fast conjunctions the 60 s grid
#: steps straight over.
FINE_STEP_SECONDS = 5

#: brentq refinement can only find a closer approach than any grid sample, so
#: the pipeline's miss distance must not exceed the 5 s grid minimum by more
#: than this (slack for the float32 sweep and the two propagation code paths).
REFINE_TOLERANCE_KM = 0.05

N_OBJECTS = 200
LEO_APOGEE_CUTOFF_KM = 2000.0
LEO_WEIGHT = 4.0  # sampled 4x as often as higher orbits -> "weighted toward LEO"
RNG_SEED = 20260829

# Any pair whose 3-D separation ever drops below this MUST survive the
# filter, not just as policy but by construction: a 3-D separation < D means
# the two geocentric radii differ by < D at that instant, and mean perigee/
# apogee sit within ~20 km of the osculating radius under J2, so
# `perigee_A - apogee_B < D + 40` < pad_km (100). Chosen below that bound so
# the check is a hard invariant, and non-vacuous (this sample has ~27 such
# pairs) unlike the sub-10-km set, which is often empty over just 6 hours.
GUARANTEED_KEEP_KM = 50.0


@pytest.fixture(scope="module")
def sample_objects() -> list[CatalogObject]:
    if not CACHE_TLE.exists():
        pytest.skip(f"cached catalogue not present: {CACHE_TLE}")

    triples = parse_tle_block(CACHE_TLE.read_text(encoding="utf-8", errors="replace"))
    triples = [t for t in triples if validate_tle_pair(t[1], t[2])]
    catalog = build_catalog_objects(triples, now_utc=NOW_UTC)

    # De-duplicate by NORAD id (a snapshot can repeat one).
    by_id: dict[int, CatalogObject] = {}
    for obj in catalog:
        by_id.setdefault(obj.norad_id, obj)
    catalog = list(by_id.values())
    assert len(catalog) >= N_OBJECTS, len(catalog)

    apogee_km = np.array([obj.apogee_km for obj in catalog])
    weights = np.where(apogee_km < LEO_APOGEE_CUTOFF_KM, LEO_WEIGHT, 1.0)
    weights /= weights.sum()

    rng = np.random.default_rng(RNG_SEED)
    idx = rng.choice(len(catalog), size=N_OBJECTS, replace=False, p=weights)
    return [catalog[int(i)] for i in idx]


@pytest.fixture(scope="module")
def propagated(
    sample_objects: list[CatalogObject],
) -> tuple[CatalogEphemeris, list[CatalogObject]]:
    """Propagate once; brute force and filtered path share this ephemeris.

    Objects whose SGP4 propagation fails are dropped by ``propagate_catalog``;
    both comparison paths then operate on exactly the survivor set.
    """
    ephem = propagate_catalog(sample_objects, START, HOURS, STEP_SECONDS)
    by_id = {obj.norad_id: obj for obj in sample_objects}
    survivors = [by_id[int(nid)] for nid in ephem.norad_ids]
    return ephem, survivors


def _all_pair_min_separations(
    positions_km: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Minimum separation over time for every i<j row pair.

    Args:
        positions_km: (n, n_steps, 3) GCRS positions, km.

    Returns:
        ``(i_idx, j_idx, min_sep_km)`` — parallel arrays, one entry per
        unordered pair. One Python loop over rows (not a double loop);
        each iteration is a vectorised distance-over-time reduction.
    """
    n = positions_km.shape[0]
    i_chunks: list[np.ndarray] = []
    j_chunks: list[np.ndarray] = []
    sep_chunks: list[np.ndarray] = []
    for i in range(n - 1):
        delta = positions_km[i + 1 :] - positions_km[i]  # (n-i-1, n_steps, 3)
        sep_over_time = np.sqrt(np.einsum("ptc,ptc->pt", delta, delta))
        i_chunks.append(np.full(n - i - 1, i, dtype=np.int64))
        j_chunks.append(np.arange(i + 1, n, dtype=np.int64))
        sep_chunks.append(sep_over_time.min(axis=1))
    return (
        np.concatenate(i_chunks),
        np.concatenate(j_chunks),
        np.concatenate(sep_chunks),
    )


def test_filter_discards_nothing_real(
    propagated: tuple[CatalogEphemeris, list[CatalogObject]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    ephem, survivors = propagated
    positions_km = np.ascontiguousarray(ephem.position_km, dtype=np.float64)
    norad_ids = ephem.norad_ids.astype(np.int64)
    row_of = {int(nid): row for row, nid in enumerate(norad_ids)}

    # 1. BRUTE FORCE — every pair, no filtering.
    bi, bj, bsep = _all_pair_min_separations(positions_km)
    brute_close: set[tuple[int, int]] = set()
    brute_near: set[tuple[int, int]] = set()
    for a, b, sep in zip(bi.tolist(), bj.tolist(), bsep.tolist()):
        id_a, id_b = int(norad_ids[a]), int(norad_ids[b])
        pair = (min(id_a, id_b), max(id_a, id_b))
        if sep < SCREENING_THRESHOLD_KM:
            brute_close.add(pair)
        if sep < GUARANTEED_KEEP_KM:
            brute_near.add(pair)

    # 2. FILTERED — min separation only for pairs the filter keeps.
    result = apogee_perigee_filter(survivors)
    surviving_pairs = set(result.pairs)
    filtered_close: set[tuple[int, int]] = set()
    for id_lo, id_hi in result.pairs:
        a, b = row_of[id_lo], row_of[id_hi]
        delta = positions_km[a] - positions_km[b]
        min_sep_km = float(np.sqrt(np.einsum("tc,tc->t", delta, delta)).min())
        if min_sep_km < SCREENING_THRESHOLD_KM:
            filtered_close.add((id_lo, id_hi))

    # 3. ASSERT: the filtered path finds exactly the brute-force sub-10-km
    #    set (the spec check), and — the non-vacuous part — every genuinely
    #    near pair (< 50 km) survived filtering at all.
    missed_near = brute_near - surviving_pairs
    assert not missed_near, (
        f"apogee_perigee_filter discarded {len(missed_near)} pair(s) that "
        f"brute force shows approaching within {GUARANTEED_KEEP_KM:g} km: "
        f"{sorted(missed_near)[:10]}"
    )
    assert filtered_close == brute_close, (
        f"filtered != brute for sub-{SCREENING_THRESHOLD_KM:g}km set; "
        f"only in brute: {sorted(brute_close - filtered_close)[:10]}; "
        f"only in filtered: {sorted(filtered_close - brute_close)[:10]}"
    )

    reduction = 1.0 - result.survival_ratio
    with capsys.disabled():
        print(
            f"\n[filter_correctness] {len(survivors)} objects, "
            f"{bi.size} pairs -> {result.surviving_pairs} survive filtering "
            f"({result.survival_ratio:.2%} kept, {reduction:.2%} discarded). "
            f"Brute-force sub-{SCREENING_THRESHOLD_KM:g}km pairs: {len(brute_close)} "
            f"(filtered path found {len(filtered_close)}); "
            f"sub-{GUARANTEED_KEEP_KM:g}km pairs: {len(brute_near)}, all retained."
        )


@pytest.fixture(scope="module")
def fine_reference_min_sep(
    propagated: tuple[CatalogEphemeris, list[CatalogObject]],
) -> dict[tuple[int, int], float]:
    """Minimum separation per pair from a 5 s brute-force propagation.

    The ground truth the 60 s screening pipeline is checked against: because a
    sampled separation is an upper bound on the true minimum, any pair below
    the threshold on this fine grid is unarguably a real close approach.
    """
    _ephem60, survivors = propagated
    ephem = propagate_catalog(survivors, START, HOURS, FINE_STEP_SECONDS)
    positions_km = np.ascontiguousarray(ephem.position_km, dtype=np.float64)
    norad_ids = ephem.norad_ids.astype(np.int64)

    i_idx, j_idx, min_sep_km = _all_pair_min_separations(positions_km)
    out: dict[tuple[int, int], float] = {}
    for a, b, sep in zip(i_idx.tolist(), j_idx.tolist(), min_sep_km.tolist()):
        lo, hi = sorted((int(norad_ids[a]), int(norad_ids[b])))
        out[(lo, hi)] = float(sep)
    return out


def test_three_pass_pipeline_finds_every_fine_grid_event(
    propagated: tuple[CatalogEphemeris, list[CatalogObject]],
    fine_reference_min_sep: dict[tuple[int, int], float],
    capsys: pytest.CaptureFixture[str],
) -> None:
    ephem, survivors = propagated
    positions_km = np.ascontiguousarray(ephem.position_km, dtype=np.float64)
    norad_ids = ephem.norad_ids.astype(np.int64)
    row_of = {int(nid): row for row, nid in enumerate(norad_ids)}
    objects_by_id = {obj.norad_id: obj for obj in survivors}

    # Every unordered survivor pair is a screening candidate: this test
    # exercises screen.py on its own, not the coarse filter.
    candidates = [
        CandidatePair(
            primary_norad_id=lo,
            secondary_norad_id=hi,
            min_separation_km=float("inf"),
        )
        for lo, hi in (
            (min(a.norad_id, b.norad_id), max(a.norad_id, b.norad_id))
            for i, a in enumerate(survivors)
            for b in survivors[i + 1 :]
        )
    ]

    results = screen_candidates(
        objects_by_id,
        candidates,
        start=START,
        window_hours=float(HOURS),
        coarse_step_seconds=float(STEP_SECONDS),
        threshold_km=SCREENING_THRESHOLD_KM,
    )
    pipeline_best: dict[tuple[int, int], float] = {}
    for r in results:
        pair = (
            min(r.primary_norad_id, r.secondary_norad_id),
            max(r.primary_norad_id, r.secondary_norad_id),
        )
        pipeline_best[pair] = min(pipeline_best.get(pair, math.inf), r.miss_distance_km)

    # Events per the 5 s reference (restricted to survivors present in both
    # propagations). True minimum <= 5 s-sampled minimum, so every one of
    # these is a genuine sub-threshold conjunction.
    reference_events = {
        pair: m
        for pair, m in fine_reference_min_sep.items()
        if m < SCREENING_THRESHOLD_KM and pair[0] in row_of and pair[1] in row_of
    }
    assert reference_events, (
        f"5 s reference found no sub-{SCREENING_THRESHOLD_KM:g}km approach in "
        f"this sample; the screening assertion would be vacuous "
        f"(fixture or selection changed?)"
    )

    # 60 s brute force for exactly those pairs. The rewrite exists because
    # these are the approaches screen.py's own 60 s grid cannot see.
    blind_to_60s: list[tuple[tuple[int, int], float, float]] = []
    for pair, m5 in reference_events.items():
        delta = positions_km[row_of[pair[0]]] - positions_km[row_of[pair[1]]]
        min_60s = float(np.sqrt(np.einsum("tc,tc->t", delta, delta)).min())
        if min_60s >= SCREENING_THRESHOLD_KM:
            blind_to_60s.append((pair, m5, min_60s))
    assert blind_to_60s, (
        "every 5 s event is also visible at 60 s in this sample, so it does "
        "not exercise the fast-conjunction miss the threshold padding prevents"
    )

    # THE ASSERTION: the padded three-pass pipeline, still sampling at 60 s,
    # recovers every event the 5 s reference finds...
    missed = sorted(pair for pair in reference_events if pair not in pipeline_best)
    assert not missed, (
        f"three-pass pipeline missed {len(missed)} sub-{SCREENING_THRESHOLD_KM:g}km "
        f"approach(es) the 5 s reference found: "
        f"{[(p, round(reference_events[p], 3)) for p in missed[:10]]}. "
        f"The threshold padding is too small — fix the padding, not this test."
    )
    # ...and refines each to no worse than the 5 s grid saw.
    worse = {
        pair: (pipeline_best[pair], m5)
        for pair, m5 in reference_events.items()
        if pipeline_best[pair] > m5 + REFINE_TOLERANCE_KM
    }
    assert not worse, (
        f"pipeline miss distance exceeds the 5 s grid minimum (refinement can "
        f"only improve on a sample) for: "
        f"{[(p, round(a, 3), round(b, 3)) for p, (a, b) in list(worse.items())[:10]]}"
    )

    with capsys.disabled():
        print(
            f"\n[screen_correctness] {len(survivors)} objects, "
            f"{len(candidates)} candidate pairs; 5 s-reference sub-"
            f"{SCREENING_THRESHOLD_KM:g}km events: {len(reference_events)}, "
            f"of which {len(blind_to_60s)} invisible at 60 s "
            f"(worst 60 s miss {max(m for _, _, m in blind_to_60s):.1f} km). "
            f"Three-pass pipeline recovered all {len(reference_events)}."
        )
