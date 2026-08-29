"""Fine screening: exact TCA and miss geometry for coarse-filter survivors.

Two stages:

COARSE SWEEP
    All coarse-filter survivors are re-propagated **once**, together, on the
    shared ``coarse_step_seconds`` grid (typically 60 s) via
    :func:`prahari_orbital.propagate.propagate_catalog`, and every pair is swept
    against that one ``(n_objects, n_steps, 3)`` GCRS position array — no Python
    loop over timesteps.

    Sampling the separation on a discrete grid and testing it directly against
    the 10 km threshold is *not* safe: two objects closing at 15 km/s move
    ~900 km between 60 s samples, so a sub-kilometre true miss can read as
    hundreds of km at every sample and be discarded — a silent missed warning.
    So each pass pads the threshold by the largest distance the separation can
    move between samples. The true minimum lies within ``dt / 2`` of some
    sample and separation changes at no more than the relative speed, hence::

        keep pair if  d_sampled < threshold + v_bound * (dt / 2)

    ``v_bound(i, j) = v_max[i] + v_max[j]`` (triangle inequality), with
    ``v_max`` each object's peak speed over the window — O(n_objects), computed
    once from the ephemeris velocity array, never per-pair across all steps.

    ``screen_candidates`` (batch) runs this as three passes; ``screen_pair``
    (one pair) runs the single-pass equivalent:

      * PASS 1 — stride 5 (dt = 300 s), pad ``v_bound * 150``; gates every pair.
      * PASS 2 — stride 1 (dt = 60 s), pad ``v_bound * 30``; pass-1 survivors
        only. Every local minimum of the padded curve is a candidate TCA.
      * PASS 3 — brentq refinement (below) of each pass-2 local minimum.

    Each pass is rigorous: any pair carried forward is guaranteed to include
    every true minimum below the threshold. Passes 1–2 work in squared distance
    in float32, accumulated one axis at a time; refinement stays float64. A
    refined approach is reported only when its exact miss distance is below the
    (unpadded) screening threshold — the padding widens the net, it does not
    loosen what counts as an event.

FINE REFINEMENT
    At the true time of closest approach the range stops changing, so the
    relative range-rate is zero::

        f(t) = r_rel(t) . v_rel(t) / |r_rel(t)|          (range_rate below)

    with ``r_rel = pos_secondary - pos_primary`` and ``v_rel`` likewise. ``f``
    is negative while the pair is closing and positive while opening, so it
    crosses zero at TCA. For each coarse local minimum we bracket that zero
    with the grid samples either side of the minimum and solve with
    ``scipy.optimize.brentq``. ``r_rel`` / ``v_rel`` at an arbitrary trial
    epoch come from calling SGP4 directly for the two objects at that instant
    (:func:`_state_at`) — the 60 s grid is never interpolated.

Each refined approach becomes one :class:`ScreeningResult`: exact TCA, miss
distance, relative speed, and the miss vector decomposed into the primary's
RIC axes via :func:`prahari_orbital.frames.rtn_basis`. ``scoring.py`` turns a
:class:`ScreeningResult` into a contract ``ConjunctionEvent``.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

import numpy as np
from scipy.optimize import brentq
from skyfield.api import EarthSatellite, Time, load
from skyfield.timelib import Timescale

from prahari_orbital import frames
from prahari_orbital.filters import SCREENING_THRESHOLD_KM, CandidatePair
from prahari_orbital.frames import StateVector
from prahari_orbital.models import CatalogObject
from prahari_orbital.propagate import propagate_catalog, propagate_one

#: Coarse-sweep sampling step, seconds. Matches the coarse filter's grid.
COARSE_STEP_SECONDS = 60.0

#: Standard screening look-ahead, hours (see propagate.make_time_grid).
SCREENING_WINDOW_HOURS = 72.0

#: brentq absolute tolerance on the TCA, in seconds (~1 microsecond).
_TCA_XTOL_SECONDS = 1e-6

#: Pass 1 subsamples the coarse grid by this stride: dt = 5 x
#: COARSE_STEP_SECONDS = 300 s. Pass 2 runs at full resolution (stride 1).
_PASS1_STRIDE = 5

#: Pair-chunk sizes for the two vectorised sweeps, sized so one chunk's
#: (n_pairs, n_steps) float32 squared-distance array is ~200 MB:
#:   pass 1  -> ~865 steps  -> 50_000 pairs  (~0.17 GB)
#:   pass 2  -> ~4321 steps -> 10_000 pairs  (~0.17 GB)
#: Deliberately not one shared value — the step counts differ 5x.
_PASS1_PAIR_CHUNK = 50_000
_PASS2_PAIR_CHUNK = 10_000


@dataclass(frozen=True)
class ScreeningResult:
    """Exact close-approach geometry for one approach, ready for scoring.py.

    One instance per *distinct* close approach — a pair that approaches three
    times over the window yields three results, each with its own ``tca``.

    Units: ``tca`` as Skyfield ``Time``; distances km; velocity km/s.
    ``radial_km`` / ``in_track_km`` / ``cross_track_km`` are the miss vector
    (secondary relative to primary, at TCA) projected onto the primary's RIC
    axes — radial, in-track (transverse), cross-track (normal) — built by
    :func:`prahari_orbital.frames.rtn_basis`. Same names/signs as
    ``conjunction.schema.json``. By construction
    ``radial_km**2 + in_track_km**2 + cross_track_km**2 == miss_distance_km**2``
    (the RIC axes are orthonormal).
    """

    primary_norad_id: int
    secondary_norad_id: int
    tca: Time
    miss_distance_km: float
    relative_velocity_km_s: float
    radial_km: float
    in_track_km: float
    cross_track_km: float


@lru_cache(maxsize=1)
def _timescale() -> Timescale:
    """Skyfield timescale from bundled data (no network). Cached."""
    return load.timescale()


@lru_cache(maxsize=8192)
def _satellite_cached(tle_line1: str, tle_line2: str, name: str) -> EarthSatellite:
    """Skyfield ``EarthSatellite`` for a TLE, memoised on the raw element lines.

    Fine refinement evaluates each object at many trial epochs; caching the
    ``EarthSatellite`` keeps that to one SGP4 model init per object per run.
    """
    return EarthSatellite(tle_line1, tle_line2, name, _timescale())


def _state_at(obj: CatalogObject, t: Time) -> tuple[np.ndarray, np.ndarray]:
    """GCRS position (km) and velocity (km/s) of ``obj`` at instant(s) ``t``.

    Skyfield's ``EarthSatellite.at()`` already returns a geocentric state
    referred to **GCRS** (the TEME->GCRS rotation happens inside Skyfield),
    exactly as :func:`prahari_orbital.propagate.propagate_one` does — no frame
    maths is hand-rolled here, per ``services/orbital/CLAUDE.md``.

    Args:
        obj: catalogue object; only ``tle_line1`` / ``tle_line2`` / ``name``
            are read.
        t: Skyfield ``Time``, scalar or shape (N,).

    Returns:
        ``(position_km, velocity_km_s)``. Shapes are (3,) for scalar ``t`` and
        (N, 3) for a length-N ``Time``. Units km and km/s, frame GCRS.
    """
    geocentric = _satellite_cached(obj.tle_line1, obj.tle_line2, obj.name).at(t)
    pos = np.asarray(geocentric.position.km, dtype=np.float64)
    vel = np.asarray(geocentric.velocity.km_per_s, dtype=np.float64)
    return (pos.T if pos.ndim == 2 else pos, vel.T if vel.ndim == 2 else vel)


def range_rate(
    primary: CatalogObject,
    secondary: CatalogObject,
    t: Time,
) -> float:
    """Signed relative range-rate between two objects at instant ``t``.

    ``d(range)/dt = (r_rel . v_rel) / |r_rel|`` with
    ``r_rel = pos_secondary - pos_primary`` and ``v_rel`` likewise, both in
    GCRS. Negative while closing, positive while opening, zero at TCA. This is
    the function :func:`find_tca` root-finds over.

    Args:
        primary: first object.
        secondary: second object.
        t: single Skyfield ``Time`` instant.

    Returns:
        Range rate, km/s. Negative = closing.
    """
    r_p, v_p = _state_at(primary, t)
    r_s, v_s = _state_at(secondary, t)
    r_rel = r_s - r_p
    v_rel = v_s - v_p
    distance_km = float(np.linalg.norm(r_rel))
    return float(np.dot(r_rel, v_rel) / distance_km)


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
        search_start: lower bound of the bracket — must have
            ``range_rate < 0`` (closing); typically the coarse grid sample
            immediately before a coarse-separation local minimum.
        search_end: upper bound — must have ``range_rate > 0`` (opening);
            typically the sample immediately after.

    Returns:
        Skyfield ``Time`` at which ``range_rate`` crosses zero (the TCA),
        located to within ~1 microsecond.

    Raises:
        ValueError: ``search_end`` is not after ``search_start``, or
            ``range_rate`` is not ``< 0`` at the start and ``> 0`` at the end
            (a bad bracket — the local-minimum detection in
            :func:`screen_candidates` handed us something that is not a
            closing->opening transition).
    """
    ts = _timescale()
    start_tt = float(search_start.tt)
    span_seconds = (float(search_end.tt) - start_tt) * 86400.0
    if span_seconds <= 0.0:
        raise ValueError(
            f"find_tca: search_end must be after search_start "
            f"(span {span_seconds:.3e} s) for NORAD "
            f"{primary.norad_id}/{secondary.norad_id}"
        )

    def f(offset_seconds: float) -> float:
        return range_rate(
            primary, secondary, ts.tt_jd(start_tt + offset_seconds / 86400.0)
        )

    f_start = f(0.0)
    f_end = f(span_seconds)
    if f_start == 0.0:
        return search_start
    if f_end == 0.0:
        return search_end
    if not (f_start < 0.0 < f_end):
        raise ValueError(
            f"find_tca: range_rate is not a closing->opening transition across "
            f"the bracket for NORAD {primary.norad_id}/{secondary.norad_id} "
            f"(start {f_start:.6e} km/s, end {f_end:.6e} km/s); bad coarse bracket"
        )

    root_seconds = brentq(
        f, 0.0, span_seconds, xtol=_TCA_XTOL_SECONDS, rtol=8.881784197001252e-16
    )
    return ts.tt_jd(start_tt + float(root_seconds) / 86400.0)


def _result_at_tca(
    primary: CatalogObject,
    secondary: CatalogObject,
    tca: Time,
) -> ScreeningResult:
    """Full close-approach geometry at a known TCA.

    Evaluates both objects at ``tca`` via SGP4, forms the miss vector
    ``r_rel`` (secondary relative to primary, GCRS, km) and relative velocity
    ``v_rel``, and projects ``r_rel`` onto the primary's RIC axes with
    :func:`prahari_orbital.frames.rtn_basis` (rows [R, T, N] = radial,
    in-track, cross-track).
    """
    r_p, v_p = _state_at(primary, tca)
    r_s, v_s = _state_at(secondary, tca)
    r_rel = r_s - r_p
    v_rel = v_s - v_p

    ric = frames.rtn_basis(
        StateVector(position_km=r_p, velocity_km_s=v_p, frame="GCRS", time=tca)
    ) @ r_rel

    return ScreeningResult(
        primary_norad_id=primary.norad_id,
        secondary_norad_id=secondary.norad_id,
        tca=tca,
        miss_distance_km=float(np.linalg.norm(r_rel)),
        relative_velocity_km_s=float(np.linalg.norm(v_rel)),
        radial_km=float(ric[0]),
        in_track_km=float(ric[1]),
        cross_track_km=float(ric[2]),
    )


def _coarse_separation(
    primary: CatalogObject,
    secondary: CatalogObject,
    *,
    start: datetime,
    window_hours: float,
    step_seconds: float,
) -> tuple[Time, np.ndarray]:
    """Vectorised 3-D separation of the pair over the coarse grid.

    One :func:`propagate_one` call per object, then a single array norm — no
    Python loop over timesteps.

    Args:
        primary: first object.
        secondary: second object.
        start: grid start, timezone-aware UTC.
        window_hours: total span, hours.
        step_seconds: grid spacing, seconds.

    Returns:
        ``(times, separation_km)`` — ``times`` the shared Skyfield ``Time``
        grid, ``separation_km`` its shape-(n_steps,) GCRS separation in km.
    """
    hours = round(window_hours)
    step = round(step_seconds)
    ephem_primary = propagate_one(primary, start, hours, step)
    ephem_secondary = propagate_one(secondary, start, hours, step)
    delta = ephem_secondary.position_km - ephem_primary.position_km
    separation_km = np.sqrt(np.einsum("ij,ij->i", delta, delta))
    return ephem_primary.times, separation_km


def _sub_threshold_local_minima(
    separation_km: np.ndarray,
    threshold_km: float,
) -> list[int]:
    """Interior indices where the separation curve bottoms out below threshold.

    A point ``i`` qualifies when ``sep[i] < sep[i-1]`` and ``sep[i] <= sep[i+1]``
    and ``sep[i] < threshold_km``. The strict-left / non-strict-right test
    reports only the leading edge of a flat minimum, so a plateau counts once.
    An approach whose minimum falls on grid index 0 or ``n-1`` is not
    detected; over a 72 h / 60 s grid that edge case is negligible.
    """
    n = separation_km.size
    if n < 3:
        return []
    interior = np.arange(1, n - 1)
    here = separation_km[interior]
    is_minimum = (here < separation_km[interior - 1]) & (here <= separation_km[interior + 1])
    below = here < threshold_km
    return [int(i) for i in interior[is_minimum & below]]


def _local_minima_below_sq(
    d2_row: np.ndarray,
    padded_threshold_sq: float,
) -> list[int]:
    """Squared-distance analogue of :func:`_sub_threshold_local_minima`.

    A point ``i`` qualifies when ``d2[i] < d2[i-1]``, ``d2[i] <= d2[i+1]`` and
    ``d2[i] <= padded_threshold_sq``. ``padded_threshold_sq`` is
    ``(threshold_km + v_bound * dt / 2) ** 2`` for the pair — the squared,
    closure-padded screening threshold — so no true sub-threshold minimum is
    dropped before refinement. Same strict-left / non-strict-right rule (a
    plateau counts once); indices 0 and ``n-1`` are never reported, so every
    returned ``i`` has valid ``i-1`` / ``i+1`` neighbours for bracketing.
    """
    n = d2_row.size
    if n < 3:
        return []
    interior = np.arange(1, n - 1)
    here = d2_row[interior]
    is_minimum = (here < d2_row[interior - 1]) & (here <= d2_row[interior + 1])
    below = here <= padded_threshold_sq
    return [int(i) for i in interior[is_minimum & below]]


def screen_pair(
    primary: CatalogObject,
    secondary: CatalogObject,
    candidate: CandidatePair,
    *,
    coarse_step_seconds: float = COARSE_STEP_SECONDS,
    start: datetime,
    window_hours: float = SCREENING_WINDOW_HOURS,
) -> ScreeningResult:
    """Fine-screen a single pair and return its closest approach.

    Runs the coarse sweep + fine refinement described in the module docstring
    and returns the single :class:`ScreeningResult` with the smallest miss
    distance. Use :func:`screen_candidates` when every distinct approach is
    wanted, not just the closest.

    Args:
        primary: first object.
        secondary: second object.
        candidate: coarse-filter output for this pair; its NORAD ids must
            match ``primary`` / ``secondary``.
        coarse_step_seconds: coarse-sweep grid spacing, seconds.
        start: screening-window start, timezone-aware UTC.
        window_hours: screening-window span, hours.

    Returns:
        The lowest-miss-distance :class:`ScreeningResult` for the pair.

    Raises:
        ValueError: the candidate's ids do not match the two objects, or no
            approach in the window produced a usable TCA bracket.
    """
    pair_ids = {primary.norad_id, secondary.norad_id}
    if {candidate.primary_norad_id, candidate.secondary_norad_id} != pair_ids:
        raise ValueError(
            f"screen_pair: candidate ids "
            f"{candidate.primary_norad_id}/{candidate.secondary_norad_id} do not "
            f"match objects {primary.norad_id}/{secondary.norad_id}"
        )

    times, separation_km = _coarse_separation(
        primary,
        secondary,
        start=start,
        window_hours=window_hours,
        step_seconds=coarse_step_seconds,
    )

    minima = _sub_threshold_local_minima(separation_km, SCREENING_THRESHOLD_KM)
    if not minima:
        # No sub-threshold dip: fall back to the global grid minimum so the
        # pair still yields its best geometry (the caller decided it was worth
        # screening).
        global_min = int(np.clip(np.argmin(separation_km), 1, separation_km.size - 2))
        minima = [global_min]

    results: list[ScreeningResult] = []
    for i in minima:
        try:
            tca = find_tca(
                primary, secondary, search_start=times[i - 1], search_end=times[i + 1]
            )
        except ValueError:
            continue
        results.append(_result_at_tca(primary, secondary, tca))

    if not results:
        raise ValueError(
            f"screen_pair: no usable TCA bracket for NORAD "
            f"{primary.norad_id}/{secondary.norad_id} over {window_hours:g} h"
        )
    return min(results, key=lambda r: r.miss_distance_km)


def screen_candidates(
    objects_by_id: dict[int, CatalogObject],
    candidates: list[CandidatePair],
    *,
    coarse_step_seconds: float = COARSE_STEP_SECONDS,
    start: datetime,
    window_hours: float = SCREENING_WINDOW_HOURS,
    threshold_km: float = SCREENING_THRESHOLD_KM,
) -> list[ScreeningResult]:
    """Fine-screen every coarse-filter survivor, one result per close approach.

    All referenced objects are re-propagated **once**, together, on the coarse
    grid (:func:`prahari_orbital.propagate.propagate_catalog`), then every pair
    is swept against that shared ``(n_objects, n_steps, 3)`` position array in
    the three padded passes described in the module docstring:

      1. stride 5 (dt = 300 s), threshold padded by ``v_bound * 150`` — gates
         every pair;
      2. stride 1 (dt = 60 s), threshold padded by ``v_bound * 30`` — pass-1
         survivors only; every local minimum of the padded squared-distance
         curve is a candidate TCA;
      3. :func:`find_tca` / brentq refinement of each pass-2 local minimum.

    The padding (``v_bound = v_max[i] + v_max[j]``, from each object's peak
    speed over the window) guarantees no true sub-``threshold_km`` approach is
    dropped by grid sampling. A refined approach is kept only when its exact
    miss distance is below ``threshold_km`` — padded selection cannot inflate
    the event count. Passes 1–2 run in float32 squared distance, chunked to
    ~0.2 GB per sweep (``_PASS1_PAIR_CHUNK`` / ``_PASS2_PAIR_CHUNK``);
    refinement is float64. Survivor count and wall time are printed to stderr
    after each pass.

    A pair with several approaches across the window contributes several
    :class:`ScreeningResult`\\ s.

    Args:
        objects_by_id: catalogue keyed by ``norad_id``. A candidate naming an
            id not present here is logged to stderr and skipped.
        candidates: output of ``filters.coarse_filter``.
        coarse_step_seconds: coarse-sweep grid spacing, seconds (the stride-1
            step; pass 1 uses 5x this).
        start: screening-window start, timezone-aware UTC.
        window_hours: screening-window span, hours.
        threshold_km: a refined approach is reported when its exact miss
            distance is below this. Each pass keeps pairs / minima out to
            ``threshold_km`` plus its closure pad.

    Returns:
        Flat list of :class:`ScreeningResult`, one per distinct refined
        approach, in candidate order then chronological order within a pair.
        A pair with no sub-threshold approach contributes nothing, silently
        (the common case at scale). Brackets that turn out not to straddle a
        closing->opening transition (see :func:`find_tca`), and candidates
        naming an unknown NORAD id or an object that failed the shared
        propagation, are logged to stderr and skipped, never fatal to the batch.
    """
    # 1. Resolve candidates -> the set of objects that must be propagated.
    valid_candidates: list[CandidatePair] = []
    valid_objects: list[tuple[CatalogObject, CatalogObject]] = []
    to_propagate: dict[int, CatalogObject] = {}
    for candidate in candidates:
        primary = objects_by_id.get(candidate.primary_norad_id)
        secondary = objects_by_id.get(candidate.secondary_norad_id)
        if primary is None or secondary is None:
            missing = (
                candidate.primary_norad_id
                if primary is None
                else candidate.secondary_norad_id
            )
            print(
                f"[screen_candidates] candidate "
                f"{candidate.primary_norad_id}/{candidate.secondary_norad_id} "
                f"names unknown NORAD id {missing}; skipped",
                file=sys.stderr,
            )
            continue
        valid_candidates.append(candidate)
        valid_objects.append((primary, secondary))
        to_propagate.setdefault(primary.norad_id, primary)
        to_propagate.setdefault(secondary.norad_id, secondary)

    if not valid_candidates:
        return []

    # 2. One shared re-propagation on the coarse (stride-1) grid.
    hours = round(window_hours)
    step = round(coarse_step_seconds)
    try:
        ephem = propagate_catalog(list(to_propagate.values()), start, hours, step)
    except ValueError as exc:
        print(
            f"[screen_candidates] shared propagation produced no usable "
            f"objects ({exc}); no pairs screened",
            file=sys.stderr,
        )
        return []

    row_of = {int(nid): row for row, nid in enumerate(ephem.norad_ids)}

    # Drop candidates whose objects fell out of the shared propagation
    # (decayed / unparseable TLE -- listed in ephem.failures).
    kept_objects: list[tuple[CatalogObject, CatalogObject]] = []
    pair_rows: list[tuple[int, int]] = []
    for primary, secondary in valid_objects:
        try:
            pair_rows.append((row_of[primary.norad_id], row_of[secondary.norad_id]))
        except KeyError as exc:
            print(
                f"[screen_candidates] {primary.norad_id}/{secondary.norad_id}: "
                f"NORAD id {exc} failed the shared propagation; skipped",
                file=sys.stderr,
            )
            continue
        kept_objects.append((primary, secondary))

    if not pair_rows:
        return []

    rows = np.asarray(pair_rows, dtype=np.int64)
    pi = rows[:, 0]
    pj = rows[:, 1]
    n_pairs = rows.shape[0]

    # float32 positions for the two sweeps (sub-metre at LEO radii, negligible
    # against a padded threshold of hundreds of km); the per-object speed
    # bound stays float64.
    pos32 = np.ascontiguousarray(ephem.position_km, dtype=np.float32)
    v_max = np.linalg.norm(ephem.velocity_km_s, axis=2).max(axis=1)  # (n_obj,) km/s
    v_bound = v_max[pi] + v_max[pj]  # (n_pairs,) km/s, triangle-inequality bound

    # 3. PASS 1 -- stride 5, dt = 300 s. Gates every pair.
    stride = _PASS1_STRIDE
    dt1 = coarse_step_seconds * stride
    thr1_sq = (threshold_km + v_bound * (dt1 / 2.0)) ** 2  # (n_pairs,)
    pos1 = pos32[:, ::stride, :]

    survivor = np.zeros(n_pairs, dtype=bool)
    t0 = time.perf_counter()
    for lo in range(0, n_pairs, _PASS1_PAIR_CHUNK):
        sl = slice(lo, lo + _PASS1_PAIR_CHUNK)
        cpi, cpj = pi[sl], pj[sl]
        d2 = (pos1[cpi, :, 0] - pos1[cpj, :, 0]) ** 2
        d2 += (pos1[cpi, :, 1] - pos1[cpj, :, 1]) ** 2
        d2 += (pos1[cpi, :, 2] - pos1[cpj, :, 2]) ** 2
        survivor[sl] = d2.min(axis=1).astype(np.float64) <= thr1_sq[sl]
    pass1_idx = np.nonzero(survivor)[0]
    print(
        f"[screen_candidates] pass 1 (stride {stride}, dt {dt1:g}s): "
        f"{pass1_idx.size}/{n_pairs} pairs kept, "
        f"{time.perf_counter() - t0:.3f}s",
        file=sys.stderr,
    )

    # 4. PASS 2 -- stride 1, dt = 60 s, pass-1 survivors only.
    dt2 = coarse_step_seconds
    thr2_sq = (threshold_km + v_bound * (dt2 / 2.0)) ** 2  # (n_pairs,)

    refine_jobs: list[tuple[int, list[int]]] = []
    t0 = time.perf_counter()
    for lo in range(0, pass1_idx.size, _PASS2_PAIR_CHUNK):
        block = pass1_idx[lo : lo + _PASS2_PAIR_CHUNK]
        cpi, cpj = pi[block], pj[block]
        d2 = (pos32[cpi, :, 0] - pos32[cpj, :, 0]) ** 2
        d2 += (pos32[cpi, :, 1] - pos32[cpj, :, 1]) ** 2
        d2 += (pos32[cpi, :, 2] - pos32[cpj, :, 2]) ** 2  # (m, n_steps) float32
        cap = thr2_sq[block]
        for k in np.nonzero(d2.min(axis=1).astype(np.float64) <= cap)[0]:
            minima = _local_minima_below_sq(d2[k], float(cap[k]))
            if minima:
                refine_jobs.append((int(block[k]), minima))
    print(
        f"[screen_candidates] pass 2 (stride 1, dt {dt2:g}s): "
        f"{len(refine_jobs)}/{pass1_idx.size} pairs kept, "
        f"{time.perf_counter() - t0:.3f}s",
        file=sys.stderr,
    )

    # 5. PASS 3 -- brentq refinement of every pass-2 local minimum.
    times = ephem.times
    results: list[ScreeningResult] = []
    t0 = time.perf_counter()
    for cand_idx, minima in refine_jobs:
        primary, secondary = kept_objects[cand_idx]
        for i in minima:
            try:
                tca = find_tca(
                    primary,
                    secondary,
                    search_start=times[i - 1],
                    search_end=times[i + 1],
                )
            except ValueError as exc:
                print(
                    f"[screen_candidates] {primary.norad_id}/{secondary.norad_id} "
                    f"@ grid index {i}: {exc}",
                    file=sys.stderr,
                )
                continue
            result = _result_at_tca(primary, secondary, tca)
            if result.miss_distance_km < threshold_km:
                results.append(result)
    print(
        f"[screen_candidates] pass 3 (brentq refine): {len(results)} approaches "
        f"below {threshold_km:g} km, {time.perf_counter() - t0:.3f}s",
        file=sys.stderr,
    )
    return results
