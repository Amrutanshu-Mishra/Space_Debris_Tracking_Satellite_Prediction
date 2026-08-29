"""End-to-end conjunction-screening pipeline, with per-stage counts and timing.

Wires the workstream modules into one run:

    fetch_catalog(offline)  ->  deterministic LEO-weighted sample
      ->  propagate_catalog  ->  apogee_perigee_filter
      ->  screen_candidates  ->  score  ->  export_events (schema-validated write)

This is the demo / benchmarking entry point, not a library seam. Every stage
prints its object/pair counts and wall-clock time to stdout so the numbers go
straight into the deck.

    python -m prahari_orbital.pipeline --objects 200 --hours 72 --out events.json

Runtime is dominated by stage 5 (fine screen), which re-propagates both
objects of *every* pair that survives the analytic filter — cost grows with
the surviving-pair count times the window step count, not with ``--objects``
alone. A coarser ``--step-seconds`` is the cheapest knob for a quick run.

Note on "propagate": the task brief says ``propagate_many``; that function is
still a stubbed seam and its ``dict[int, StateVector]`` output has no consumer
here (``apogee_perigee_filter`` works off mean elements, ``screen_candidates``
re-propagates each pair internally). The implemented batch propagator
``propagate_catalog`` is used instead — it gives a real propagation timing for
the deck and drops un-propagatable (decayed / malformed) TLEs before they
reach screening.
"""

from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from prahari_orbital.filters import (
    SCREENING_THRESHOLD_KM,
    CandidatePair,
    apogee_perigee_filter,
)
from prahari_orbital.ingest import fetch_catalog
from prahari_orbital.models import CatalogObject
from prahari_orbital.propagate import propagate_catalog
from prahari_orbital.scoring import export_events, score
from prahari_orbital.screen import screen_candidates

#: Cached-catalogue location, resolved against the service root rather than the
#: caller's CWD so ``python -m prahari_orbital.pipeline`` works from anywhere.
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"

#: Objects with perigee below this are treated as "LEO" and over-sampled: that
#: is where the conjunction rate is by far the highest.
LEO_PERIGEE_CUTOFF_KM = 2000.0
#: How many times more likely a LEO object is to be picked than a higher one.
LEO_OVERSAMPLE_WEIGHT = 4.0
#: Fixed seed for the sample draw so a run is byte-for-byte repeatable.
SELECTION_SEED = 20260829


def _dedupe_by_norad_id(objects: list[CatalogObject]) -> list[CatalogObject]:
    """First occurrence wins; a single snapshot can list one NORAD id twice."""
    by_id: dict[int, CatalogObject] = {}
    for obj in objects:
        by_id.setdefault(obj.norad_id, obj)
    return list(by_id.values())


def _select_leo_weighted(
    catalogue: list[CatalogObject],
    n_objects: int,
) -> list[CatalogObject]:
    """Deterministically sample ``n_objects`` records, over-weighting LEO.

    Draw is seeded (``SELECTION_SEED``) and without replacement; the result is
    returned in ascending catalogue order so the selection — and therefore
    every downstream count — is identical run to run.

    Raises:
        ValueError: ``n_objects`` exceeds the number of unique cached records.
    """
    if n_objects > len(catalogue):
        raise ValueError(
            f"pipeline: asked for {n_objects} objects but the cached catalogue "
            f"has only {len(catalogue)} unique records"
        )
    perigee_km = np.fromiter(
        (obj.perigee_km for obj in catalogue), dtype=np.float64, count=len(catalogue)
    )
    weights = np.where(perigee_km < LEO_PERIGEE_CUTOFF_KM, LEO_OVERSAMPLE_WEIGHT, 1.0)
    weights /= weights.sum()

    rng = np.random.default_rng(SELECTION_SEED)
    picked = rng.choice(len(catalogue), size=n_objects, replace=False, p=weights)
    return [catalogue[int(i)] for i in np.sort(picked)]


def _log_stage(stage: str, detail: str, seconds: float) -> None:
    print(f"  {stage:<26}{detail:<44}{seconds:8.2f}s", flush=True)


def run(n_objects: int, hours: int, step_seconds: int, out: Path) -> None:
    """Run the whole screening pipeline and write a schema-valid event array.

    Args:
        n_objects: how many cached catalogue objects to sample (LEO-weighted,
            deterministic). Must be >= 2 and <= the unique cached record count.
        hours: screening / propagation window, hours (> 0). Used both as the
            propagation span and as ``screen_candidates``' window.
        step_seconds: coarse propagation / sweep step, seconds (> 0).
        out: destination ``.json`` file for the ``ConjunctionEvent`` array.

    Side effects:
        Prints a per-stage summary (counts + wall time) to stdout, then writes
        ``out``. Raises before writing if any event fails schema validation
        (see :func:`prahari_orbital.scoring.export_events`).
    """
    if n_objects < 2:
        raise ValueError(f"pipeline: need at least 2 objects to form a pair, got {n_objects}")
    if hours <= 0:
        raise ValueError(f"pipeline: hours must be > 0, got {hours}")
    if step_seconds <= 0:
        raise ValueError(f"pipeline: step_seconds must be > 0, got {step_seconds}")

    window_start = datetime.now(UTC)
    print(
        f"PRAHARI screening pipeline | window {hours} h @ {step_seconds}s | "
        f"start {window_start.isoformat(timespec='seconds')}"
    )
    print(f"  {'stage':<26}{'result':<44}{'wall':>9}")

    # 1. Load the cached catalogue (never touches the network).
    t0 = time.perf_counter()
    snapshot = fetch_catalog(group="active", cache_dir=CACHE_DIR, offline=True)
    catalogue = _dedupe_by_norad_id(snapshot.objects)
    _log_stage(
        "1 load catalogue",
        f"{len(catalogue)} objects  ({snapshot.source_path.name})",
        time.perf_counter() - t0,
    )

    # 2. Deterministic, LEO-weighted sample.
    t0 = time.perf_counter()
    selected = _select_leo_weighted(catalogue, n_objects)
    n_leo = sum(1 for o in selected if o.perigee_km < LEO_PERIGEE_CUTOFF_KM)
    _log_stage(
        "2 select sample",
        f"{len(selected)} objects  ({n_leo} LEO, seed {SELECTION_SEED})",
        time.perf_counter() - t0,
    )

    # 3. Batch-propagate; this also filters out decayed / unparseable TLEs.
    t0 = time.perf_counter()
    ephemeris = propagate_catalog(selected, window_start, hours, step_seconds)
    usable_ids = {int(nid) for nid in ephemeris.norad_ids}
    usable = [obj for obj in selected if obj.norad_id in usable_ids]
    objects_by_id = {obj.norad_id: obj for obj in usable}
    _log_stage(
        "3 propagate",
        f"{len(usable)} ok, {len(selected) - len(usable)} dropped (bad TLE)",
        time.perf_counter() - t0,
    )

    # 4. Analytic apogee/perigee prefilter -> candidate pairs.
    t0 = time.perf_counter()
    filtered = apogee_perigee_filter(usable)
    reduction_ratio = 1.0 - filtered.survival_ratio
    _log_stage(
        "4 apogee/perigee filter",
        f"{filtered.surviving_pairs}/{filtered.total_pairs} pairs "
        f"({reduction_ratio:.2%} cut)",
        time.perf_counter() - t0,
    )

    # 5. Fine screening: exact TCA + geometry per close approach.
    t0 = time.perf_counter()
    candidates = [
        CandidatePair(
            primary_norad_id=low_id,
            secondary_norad_id=high_id,
            min_separation_km=float("inf"),  # not measured by the analytic filter
        )
        for low_id, high_id in filtered.pairs
    ]
    results = screen_candidates(
        objects_by_id,
        candidates,
        start=window_start,
        window_hours=float(hours),
        coarse_step_seconds=float(step_seconds),
        threshold_km=SCREENING_THRESHOLD_KM,
    )
    _log_stage(
        "5 fine screen",
        f"{len(candidates)} pairs -> {len(results)} close approaches",
        time.perf_counter() - t0,
    )

    # 6. Score each approach into a contract ConjunctionEvent.
    t0 = time.perf_counter()
    screened_at = datetime.now(UTC)
    events = [
        score(
            result,
            objects_by_id[result.primary_norad_id],
            objects_by_id[result.secondary_norad_id],
            screened_at=screened_at,
        )
        for result in results
    ]
    tier_counts = Counter(event.risk_tier.value for event in events)
    tier_breakdown = "  ".join(
        f"{tier_counts.get(tier, 0)} {tier}" for tier in ("RED", "AMBER", "GREEN")
    )
    _log_stage("6 score", f"{len(events)} events  [{tier_breakdown}]", time.perf_counter() - t0)

    # 7. Validate the whole array against the frozen schema, then write.
    t0 = time.perf_counter()
    written = export_events(events, out)
    _log_stage("7 validate + write", str(written), time.perf_counter() - t0)

    print(
        "\nSUMMARY  "
        f"selected={len(selected)}  "
        f"pairs={filtered.total_pairs}  "
        f"filtered={filtered.surviving_pairs}  "
        f"reduction={reduction_ratio:.2%}  "
        f"screened={len(candidates)}  "
        f"approaches={len(results)}  "
        f"events={len(events)}  "
        f"tiers=[{tier_breakdown}]  "
        f"-> {written}"
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m prahari_orbital.pipeline",
        description=(
            "Run the end-to-end PRAHARI conjunction-screening pipeline against "
            "the cached catalogue and write a schema-valid ConjunctionEvent array."
        ),
    )
    parser.add_argument(
        "--objects",
        type=int,
        required=True,
        metavar="N",
        help="number of catalogue objects to sample (LEO-weighted, deterministic)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        required=True,
        metavar="H",
        help="screening / propagation window, hours",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        metavar="PATH",
        help="destination .json file for the ConjunctionEvent array",
    )
    parser.add_argument(
        "--step-seconds",
        type=int,
        default=60,
        metavar="S",
        help="coarse propagation / sweep step, seconds (default: 60)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    run(
        n_objects=args.objects,
        hours=args.hours,
        step_seconds=args.step_seconds,
        out=args.out,
    )


if __name__ == "__main__":
    main()
