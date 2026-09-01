"""One measured scaling point for the conjunction-screening pipeline.

Runs the real pipeline stages (``fetch_catalog`` -> deterministic LEO-weighted
sample -> chunked ``propagate_catalog`` -> block-vs-block apogee/perigee filter
-> block-vs-block ``screen_candidates`` -> ``score`` -> ``export_events``) at a
chosen catalogue size, in blocks small enough to hold peak memory under a
ceiling, and prints the per-stage funnel, the per-pair conversion rates, the
wall time per stage, and the peak OS working-set size.

    python tools/run_scaling_point.py --objects 4000 --block 2000 --hours 72 \
        --max-mem-gb 4.0 --out runs/ev_4000.json --summary runs/sum_4000.json

Not a library seam and not imported anywhere -- a benchmark harness. It
re-implements the apogee/perigee rule block-wise (identical arithmetic to
``filters.apogee_perigee_filter``, just never materialising the full
O(n^2) pair list) and drives ``screen.screen_candidates`` once per block pair
so its internal shared re-propagation only ever sees <= 2 blocks of objects.
"""

from __future__ import annotations

import argparse
import ctypes
import io
import json
import re
import time
from collections import Counter, defaultdict
from contextlib import redirect_stderr
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from prahari_orbital.filters import SCREENING_THRESHOLD_KM, CandidatePair
from prahari_orbital.ingest import fetch_catalog
from prahari_orbital.models import CatalogObject
from prahari_orbital.pipeline import (
    CACHE_DIR,
    _dedupe_by_norad_id,
    _select_leo_weighted,
)
from prahari_orbital.propagate import propagate_catalog
from prahari_orbital.scoring import export_events, score
from prahari_orbital.screen import screen_candidates

APOGEE_PERIGEE_PAD_KM = 100.0  # matches filters.apogee_perigee_filter default


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _mem_gb() -> tuple[float, float]:
    """(current, peak) working-set size of this process in GiB (Windows)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    fn = getattr(k32, "K32GetProcessMemoryInfo", None)
    if fn is None:
        fn = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    fn.restype = wintypes.BOOL

    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    if not fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return pmc.WorkingSetSize / (1024**3), pmc.PeakWorkingSetSize / (1024**3)


def peak_working_set_gb() -> float:
    return _mem_gb()[1]


class MemGuard:
    """Track peak working-set size across stages, abort if a ceiling is crossed.

    Uses the OS PeakWorkingSetSize counter (monotonic), not ``tracemalloc`` --
    ``propagate_catalog`` starts and stops its own tracemalloc trace, which
    would clobber ours.
    """

    def __init__(self, ceiling_gb: float) -> None:
        self.ceiling_gb = ceiling_gb
        self.peak_gb = 0.0

    def check(self, stage: str) -> None:
        cur, peak = _mem_gb()
        self.peak_gb = max(self.peak_gb, peak)
        print(
            f"    [mem] after {stage:<24} working set {cur:5.2f} GiB   "
            f"peak {peak:5.2f} GiB",
            flush=True,
        )
        if self.ceiling_gb and peak > self.ceiling_gb:
            print(
                f"\nABORT: peak working set {peak:.2f} GiB exceeded the "
                f"{self.ceiling_gb:.2f} GiB ceiling at stage '{stage}'.",
                flush=True,
            )
            raise SystemExit(2)


_PASS_RE = re.compile(r"pass (\d) .*?(\d+)/(\d+) pairs kept")
_PASS3_RE = re.compile(r"pass 3 \(brentq refine\): (\d+) approaches")


def _accumulate_pass_counts(stderr_text: str, into: dict[str, int]) -> None:
    for m in _PASS_RE.finditer(stderr_text):
        p, kept, seen = m.groups()
        into[f"pass{p}_in"] += int(seen)
        into[f"pass{p}_out"] += int(kept)
    for m in _PASS3_RE.finditer(stderr_text):
        into["pass3_approaches"] += int(m.group(1))


def _block_survivors(
    peri: np.ndarray,
    apo: np.ndarray,
    ids: np.ndarray,
    ai: int,
    bi: int,
    starts: list[int],
    ends: list[int],
    pad_km: float,
) -> tuple[np.ndarray, np.ndarray]:
    """(lo_id, hi_id) arrays surviving the apogee/perigee rule between two blocks.

    Identical rule to ``filters.apogee_perigee_filter``: drop a pair when
    ``perigee_A - apogee_B > pad`` or ``perigee_B - apogee_A > pad``. For the
    diagonal block (``ai == bi``) only the strict upper triangle is emitted.
    """
    sa, ea = starts[ai], ends[ai]
    sb, eb = starts[bi], ends[bi]
    pa, aa, ida = peri[sa:ea], apo[sa:ea], ids[sa:ea]
    pb, ab, idb = peri[sb:eb], apo[sb:eb], ids[sb:eb]

    clears = (pa[:, None] - ab[None, :] > pad_km) | (pb[None, :] - aa[:, None] > pad_km)
    keep = ~clears
    if ai == bi:
        keep &= np.triu(np.ones_like(keep), k=1)
    ii, jj = np.nonzero(keep)
    a_id = ida[ii]
    b_id = idb[jj]
    lo = np.minimum(a_id, b_id)
    hi = np.maximum(a_id, b_id)
    return lo, hi


def run(n_objects: int, block: int, hours: int, ceiling_gb: float, out: Path) -> dict:
    guard = MemGuard(ceiling_gb)
    window_start = datetime.now(UTC)
    step_seconds = 60
    stage_wall: dict[str, float] = {}

    t0 = time.perf_counter()
    snap = fetch_catalog(group="active", cache_dir=CACHE_DIR, offline=True)
    catalogue = _dedupe_by_norad_id(snap.objects)
    selected = _select_leo_weighted(catalogue, n_objects)
    stage_wall["load+select"] = time.perf_counter() - t0
    guard.check("load+select")

    # --- Stage: chunked propagation (bad-TLE gate), float32 -------------------
    t0 = time.perf_counter()
    usable: list[CatalogObject] = []
    for lo in range(0, len(selected), block):
        chunk = selected[lo : lo + block]
        ephem = propagate_catalog(
            chunk, window_start, hours, step_seconds, dtype=np.float32
        )
        ok = {int(n) for n in ephem.norad_ids}
        usable.extend(o for o in chunk if o.norad_id in ok)
        del ephem
        guard.check(f"propagate[{lo}:{lo + len(chunk)}]")
    stage_wall["propagate"] = time.perf_counter() - t0
    n_dropped = len(selected) - len(usable)

    # --- Stage: block-vs-block apogee/perigee filter (no O(n^2) list) --------
    t0 = time.perf_counter()
    peri = np.fromiter((o.perigee_km for o in usable), np.float64, len(usable))
    apo = np.fromiter((o.apogee_km for o in usable), np.float64, len(usable))
    ids = np.fromiter((o.norad_id for o in usable), np.int64, len(usable))
    starts = list(range(0, len(usable), block))
    ends = [min(s + block, len(usable)) for s in starts]
    n_blocks = len(starts)

    lo_parts: list[np.ndarray] = []
    hi_parts: list[np.ndarray] = []
    for ai in range(n_blocks):
        for bi in range(ai, n_blocks):
            lo_ids, hi_ids = _block_survivors(
                peri, apo, ids, ai, bi, starts, ends, APOGEE_PERIGEE_PAD_KM
            )
            if lo_ids.size:
                lo_parts.append(lo_ids)
                hi_parts.append(hi_ids)
    surv_lo = np.concatenate(lo_parts) if lo_parts else np.empty(0, np.int64)
    surv_hi = np.concatenate(hi_parts) if hi_parts else np.empty(0, np.int64)
    n_usable = len(usable)
    total_pairs = n_usable * (n_usable - 1) // 2
    surviving_pairs = int(surv_lo.size)
    stage_wall["apogee_perigee"] = time.perf_counter() - t0
    guard.check("apogee_perigee")

    # --- Stage: block-vs-block fine screening -------------------------------
    t0 = time.perf_counter()
    obj_by_id = {o.norad_id: o for o in usable}
    block_of = {
        o.norad_id: bi
        for bi, (s, e) in enumerate(zip(starts, ends))
        for o in usable[s:e]
    }
    groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    for k in range(surviving_pairs):
        a, b = int(surv_lo[k]), int(surv_hi[k])
        ba, bb = block_of[a], block_of[b]
        groups[(min(ba, bb), max(ba, bb))].append(k)

    pass_counts: dict[str, int] = Counter()
    results = []
    for (ba, bb), idxs in sorted(groups.items()):
        block_ids = set(ids[starts[ba] : ends[ba]].tolist())
        block_ids.update(ids[starts[bb] : ends[bb]].tolist())
        sub_objs = {i: obj_by_id[i] for i in block_ids}
        candidates = [
            CandidatePair(
                primary_norad_id=int(surv_lo[k]),
                secondary_norad_id=int(surv_hi[k]),
                min_separation_km=float("inf"),
            )
            for k in idxs
        ]
        buf = io.StringIO()
        with redirect_stderr(buf):
            res = screen_candidates(
                sub_objs,
                candidates,
                start=window_start,
                window_hours=float(hours),
                coarse_step_seconds=float(step_seconds),
                threshold_km=SCREENING_THRESHOLD_KM,
            )
        text = buf.getvalue()
        _accumulate_pass_counts(text, pass_counts)
        results.extend(res)
        print(
            f"    screen block ({ba},{bb}): {len(candidates)} cand -> "
            f"{len(res)} approaches",
            flush=True,
        )
        guard.check(f"screen({ba},{bb})")
    stage_wall["screen"] = time.perf_counter() - t0

    # --- Stage: score + write ---------------------------------------------
    t0 = time.perf_counter()
    screened_at = datetime.now(UTC)
    events = [
        score(r, obj_by_id[r.primary_norad_id], obj_by_id[r.secondary_norad_id],
              screened_at=screened_at)
        for r in results
    ]
    tiers = Counter(e.risk_tier.value for e in events)
    export_events(events, out)
    stage_wall["score+write"] = time.perf_counter() - t0
    guard.check("score+write")

    p1i = pass_counts.get("pass1_in", 0)
    p1o = pass_counts.get("pass1_out", 0)
    p2o = pass_counts.get("pass2_out", 0)
    p3a = pass_counts.get("pass3_approaches", 0)

    summary = {
        "objects_requested": n_objects,
        "objects_usable": n_usable,
        "objects_dropped_bad_tle": n_dropped,
        "block": block,
        "hours": hours,
        "raw_pairs": total_pairs,
        "apogee_perigee_survivors": surviving_pairs,
        "pass1_in": p1i,
        "pass1_out": p1o,
        "pass2_out_to_brentq": p2o,
        "pass3_approaches": p3a,
        "events": len(events),
        "tiers": {"RED": tiers.get("RED", 0), "AMBER": tiers.get("AMBER", 0),
                  "GREEN": tiers.get("GREEN", 0)},
        "conversion": {
            "apogee_perigee_survival": surviving_pairs / total_pairs if total_pairs else 0.0,
            "pass1_keep": p1o / p1i if p1i else 0.0,
            "pass2_keep": p2o / p1o if p1o else 0.0,
            "pass3_event_per_brentq_pair": len(events) / p2o if p2o else 0.0,
            "events_per_raw_pair": len(events) / total_pairs if total_pairs else 0.0,
        },
        "wall_seconds": stage_wall,
        "wall_total_seconds": sum(stage_wall.values()),
        "peak_working_set_gb": guard.peak_gb,
    }
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(prog="run_scaling_point.py")
    ap.add_argument("--objects", type=int, required=True)
    ap.add_argument("--block", type=int, default=2000)
    ap.add_argument("--hours", type=int, default=72)
    ap.add_argument("--max-mem-gb", type=float, default=4.0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()
    summary = run(args.objects, args.block, args.hours, args.max_mem_gb, args.out)
    summary["wallclock_seconds"] = time.perf_counter() - t_start
    args.summary.write_text(json.dumps(summary, indent=2))

    print("\n=== SCALING POINT ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
