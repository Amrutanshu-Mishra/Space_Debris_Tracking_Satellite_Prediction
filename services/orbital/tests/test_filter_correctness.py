"""The filter must discard nothing real — verified against brute force.

A false negative in :func:`apogee_perigee_filter` is silent and
unrecoverable: a genuine close approach simply never reaches ``screen.py``
and no warning is issued. So this test does not trust the filter's logic at
all. It runs the full O(N^2) brute force (every pair, minimum separation
over a real 6-hour propagation) and the filtered path side by side, and
asserts they flag the *exact same* set of sub-10-km pairs.

The comparison is against brute force only — never the filter against
itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from prahari_orbital.filters import SCREENING_THRESHOLD_KM, apogee_perigee_filter
from prahari_orbital.ingest import build_catalog_objects, parse_tle_block, validate_tle_pair
from prahari_orbital.models import CatalogObject
from prahari_orbital.propagate import CatalogEphemeris, propagate_catalog

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
