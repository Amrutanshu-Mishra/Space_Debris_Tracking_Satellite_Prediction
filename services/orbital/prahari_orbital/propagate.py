"""SGP4 wrapper: TLE -> position/velocity time series.

Owns the boundary between "TLE mean elements" and "state vectors usable by
the rest of the pipeline".

Two entry points, on purpose:

* ``propagate_one(obj, start, hours, step_seconds) -> Ephemeris`` — this
  workstream's own single-object path (ground tracks, altitude series,
  pair-screening input). Takes a frozen-contract ``CatalogObject`` and uses
  Skyfield's ``EarthSatellite.at()``, which already returns a GCRS position,
  so it needs no explicit TEME step and hand-rolls no rotation.
* ``propagate`` / ``propagate_many`` (``CatalogObject -> StateVector``,
  below) — the seam shared with ``filters.py`` / ``screen.py`` (workstream 2).
  Still stubbed; their signatures are that team's contract, not ours to
  change. They emit TEME and hand it to ``frames.teme_to_gcrs`` — nothing
  downstream of this module should ever see a raw TEME vector.
"""

from __future__ import annotations

import sys
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
from numpy.typing import DTypeLike
from sgp4.api import Satrec, SatrecArray
from skyfield.api import EarthSatellite, Time, load
from skyfield.constants import DAY_S
from skyfield.timelib import Timescale

from prahari_orbital import frames
from prahari_orbital.frames import StateVector
from prahari_orbital.models import CatalogObject

# --------------------------------------------------------------------------- #
# Single-object propagation (workstream 1).                                   #
#                                                                             #
# propagate_one / Ephemeris are this workstream's own trajectory type. The    #
# CatalogObject -> StateVector functions further down are the seam shared     #
# with filters.py / screen.py (workstream 2); their signatures stay put.      #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _timescale() -> Timescale:
    """Skyfield timescale, built from bundled data (no network). Cached."""
    return load.timescale()


def _earth_satellite(obj: CatalogObject, ts: Timescale) -> EarthSatellite:
    """Skyfield ``EarthSatellite`` from a CatalogObject's two TLE element lines.

    Args:
        obj: catalogue object. Only ``tle_line1`` / ``tle_line2`` / ``name``
            are read (the frozen-contract field names — a TLE has no separate
            ``line1``); the SGP4 model is initialised from the raw lines, not
            from the derived mean elements on the object.
        ts: Skyfield timescale.

    Returns:
        ``EarthSatellite`` whose ``.at()`` yields a GCRS-referred geocentric
        position (Skyfield performs the TEME->GCRS rotation internally).

    Units/frame: none consumed here; ``.at()`` output is km / km/s in GCRS.
    """
    return EarthSatellite(obj.tle_line1, obj.tle_line2, obj.name, ts)


@dataclass(frozen=True)
class Ephemeris:
    """One object's propagated trajectory over an evenly spaced time grid.

    Workstream-1 internal type — not a frozen contract, not in ``models.py``.
    Deliberately single-object: there is no leading "object" axis anywhere.

    Attributes:
        times: Skyfield ``Time`` array, shape (n_steps,) — the evaluation
            instants, ascending and evenly spaced.
        position_km: float64 ndarray, shape (n_steps, 3). Geocentric position
            in the **GCRS** frame ("GCRS" is the term frozen across
            ``contracts/schemas/``; it is Skyfield's canonical geocentric
            inertial frame). Units: kilometres.
        velocity_km_s: float64 ndarray, shape (n_steps, 3). Geocentric
            velocity in **GCRS**. Units: kilometres per second.
        record: the source
            :class:`~prahari_orbital.models.CatalogObject` these elements were
            propagated from.

    Units/frame: ``position_km`` / ``velocity_km_s`` are GCRS, in km and km/s.
    Every accessor below delegates its frame maths to
    :mod:`prahari_orbital.frames`, the only module permitted to convert frames.
    """

    times: Time
    position_km: np.ndarray
    velocity_km_s: np.ndarray
    record: CatalogObject

    def gcrs(self) -> np.ndarray:
        """Inertial (GCRS) position, for pair screening.

        Returns:
            float64 ndarray, shape (n_steps, 3), kilometres, **GCRS** frame.
            Value-identical to ``position_km`` (Skyfield's ``at()`` is already
            GCRS); routed through :func:`frames.gcrs_position_km` so the array
            still originates in ``frames``.

        Units/frame: km, GCRS.
        """
        return frames.gcrs_position_km(self.position_km)

    def itrf(self) -> np.ndarray:
        """Earth-fixed (ITRF / ECEF) position.

        Returns:
            float64 ndarray, shape (n_steps, 3), kilometres, **ITRF** frame.
            Converted from ``position_km`` per-step via
            :func:`frames.gcrs_to_itrf_position_km`.

        Units/frame: km, ITRF.
        """
        return frames.gcrs_to_itrf_position_km(self.position_km, self.times)

    def subpoint(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Geodetic sub-satellite track, for ground tracks.

        Returns:
            ``(latitude_deg, longitude_deg, altitude_km)``, each a float64
            ndarray of shape (n_steps,). WGS84 ellipsoid — latitude and
            longitude in degrees, altitude in km above the ellipsoid.
            Computed from ``position_km`` via :func:`frames.gcrs_to_geodetic`.

        Units/frame: degrees + km; geodetic WGS84.
        """
        lla = frames.gcrs_to_geodetic(self.position_km, self.times)
        return lla[:, 0], lla[:, 1], lla[:, 2]

    def altitude_km(self) -> np.ndarray:
        """Altitude above the WGS84 ellipsoid.

        Returns:
            float64 ndarray, shape (n_steps,), kilometres above the WGS84
            ellipsoid. This is an *ellipsoidal* height — it differs by up to
            ~21 km from ingest's spherical ``perigee_km`` / ``apogee_km``.
            Computed from ``position_km`` via :func:`frames.gcrs_to_geodetic`.

        Units/frame: km above the WGS84 ellipsoid.
        """
        return frames.gcrs_to_geodetic(self.position_km, self.times)[:, 2]


def propagate_one(
    obj: CatalogObject,
    start: datetime,
    hours: int,
    step_seconds: int,
) -> Ephemeris:
    """Propagate one object's SGP4 elements over an evenly spaced time grid.

    Builds a Skyfield ``EarthSatellite`` from ``obj.tle_line1`` /
    ``obj.tle_line2`` and samples ``satellite.at(t)`` across the grid.
    Skyfield's ``at()`` returns a geocentric position already referred to
    **GCRS**, so no TEME rotation is performed here (and none must ever be
    hand-rolled — see :mod:`prahari_orbital.frames`).

    Args:
        obj: a :class:`~prahari_orbital.models.CatalogObject` with valid
            ``tle_line1`` / ``tle_line2`` (e.g. from
            :func:`prahari_orbital.ingest.build_catalog_objects`).
        start: first sample instant. **Must be timezone-aware UTC** — a naive
            datetime raises ``ValueError``.
        hours: total span of the grid, in hours (``>= 0``); both ends inclusive.
        step_seconds: spacing between samples, in seconds (``> 0``).

    Returns:
        :class:`Ephemeris` with ``n_steps = hours * 3600 // step_seconds + 1``
        samples. ``position_km`` / ``velocity_km_s`` are float64 (n_steps, 3)
        in **GCRS**, in km and km/s; ``times`` is the Skyfield ``Time`` grid.

    Raises:
        ValueError: ``start`` is naive; ``hours`` < 0; ``step_seconds`` <= 0;
            or SGP4 reports a propagation error (surfaced as non-finite
            positions) for this object — reported with its NORAD id, never
            silently zero-filled.

    Units/frame: input ``start`` is UTC; output is km, km/s, GCRS frame.
    """
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError(
            "propagate_one: 'start' must be timezone-aware UTC, got a naive datetime"
        )
    if hours < 0:
        raise ValueError(f"propagate_one: 'hours' must be >= 0, got {hours}")
    if step_seconds <= 0:
        raise ValueError(f"propagate_one: 'step_seconds' must be > 0, got {step_seconds}")

    ts = _timescale()
    t0 = ts.from_datetime(start)
    n_steps = hours * 3600 // step_seconds + 1
    # Same grid construction as make_time_grid(): advance TT by whole-second
    # steps expressed in days, so the two entry points stay bit-compatible if
    # workstream 2's StateVector path is later reconciled with Ephemeris.
    step_days = step_seconds / 86400.0
    times = ts.tt_jd(t0.tt + np.arange(n_steps, dtype=np.float64) * step_days)

    satellite = _earth_satellite(obj, ts)
    geocentric = satellite.at(times)  # GCRS-referred, per Skyfield

    position_km = np.ascontiguousarray(geocentric.position.km.T, dtype=np.float64)
    velocity_km_s = np.ascontiguousarray(geocentric.velocity.km_per_s.T, dtype=np.float64)

    if not np.isfinite(position_km).all():
        bad = int(np.count_nonzero(~np.isfinite(position_km).all(axis=1)))
        raise ValueError(
            f"propagate_one: SGP4 produced non-finite positions for NORAD "
            f"{obj.norad_id} at {bad}/{n_steps} steps (decayed orbit or bad elements)"
        )

    return Ephemeris(
        times=times,
        position_km=position_km,
        velocity_km_s=velocity_km_s,
        record=obj,
    )


# --------------------------------------------------------------------------- #
# Batch propagation (workstream 1).                                           #
#                                                                            #
# CatalogEphemeris / propagate_catalog are the many-object analogue of       #
# Ephemeris / propagate_one -- same workstream-1-internal status, same GCRS  #
# output contract, a leading object axis added on purpose. This is NOT       #
# propagate_many(objects, times) -> dict[int, StateVector] further down:     #
# that name/signature is the frozen seam with screening (workstream 2) and   #
# is left untouched.                                                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CatalogEphemeris:
    """A whole catalogue's propagated trajectories on one shared time grid.

    Workstream-1 internal type, like :class:`Ephemeris` -- not a frozen
    contract, not in ``models.py``. The batch analogue of ``Ephemeris``: a
    leading object axis is present here on purpose (``Ephemeris`` has none).

    Attributes:
        norad_ids: int64 ndarray, shape ``(n_ok,)``. Row ``i`` of every
            array below belongs to ``norad_ids[i]``. Objects whose SGP4
            propagation failed are **absent** from this array (see
            ``failures``); they are never present as a zero or NaN row.
        position_km: ndarray, shape ``(n_ok, n_steps, 3)``, **GCRS**,
            kilometres. dtype is float64 or float32 per the ``dtype``
            argument to :func:`propagate_catalog`.
        velocity_km_s: ndarray, shape ``(n_ok, n_steps, 3)``, **GCRS**,
            kilometres per second. Same dtype as ``position_km``.
        times: Skyfield ``Time``, shape ``(n_steps,)`` -- the shared,
            evenly spaced evaluation grid.
        failures: list of ``(norad_id, reason)`` for every input record
            that could not be propagated (unparseable TLE, SGP4 error code,
            or non-finite output at any step). None of these ``norad_id``\\ s
            appear in ``norad_ids``.

    Units/frame: **GCRS**, km and km/s. "GCRS" is the frozen project term
    for Skyfield's geocentric inertial frame -- never "GCRF"
    (see ``services/orbital/CLAUDE.md``).
    """

    norad_ids: np.ndarray
    position_km: np.ndarray
    velocity_km_s: np.ndarray
    times: Time
    failures: list[tuple[int, str]]

    def save_npz(self, path: str | Path) -> None:
        """Serialise to a ``.npz`` so another process can pick the result up.

        Stores the GCRS position/velocity arrays (dtype preserved), the
        NORAD-id vector, the time grid as Skyfield-native ``(whole,
        tt_fraction)`` Julian-day pairs (lossless round-trip), the failure
        list, and the frame string. No pickled objects -- ``load_npz`` reads
        it back with ``allow_pickle=False``.

        Args:
            path: destination file. ``.npz`` is appended by numpy if absent.

        Units/frame: unchanged on disk -- km, km/s, GCRS.
        """
        failure_norad_ids = np.array(
            [nid for nid, _ in self.failures], dtype=np.int64
        )
        failure_reasons = np.array(
            [reason for _, reason in self.failures], dtype=np.str_
        )
        np.savez(
            path,
            norad_ids=np.asarray(self.norad_ids, dtype=np.int64),
            position_km=self.position_km,
            velocity_km_s=self.velocity_km_s,
            time_whole=np.asarray(self.times.whole, dtype=np.float64),
            time_tt_fraction=np.asarray(self.times.tt_fraction, dtype=np.float64),
            failure_norad_ids=failure_norad_ids,
            failure_reasons=failure_reasons,
            frame=np.array("GCRS"),
        )

    @classmethod
    def load_npz(cls, path: str | Path) -> CatalogEphemeris:
        """Reconstruct a :class:`CatalogEphemeris` written by :meth:`save_npz`.

        Args:
            path: a ``.npz`` produced by :meth:`save_npz`.

        Returns:
            The round-tripped result. ``position_km`` / ``velocity_km_s``
            keep whatever dtype (float64 / float32) they had when saved;
            ``times`` is rebuilt on this process's cached timescale.

        Raises:
            ValueError: the file's ``frame`` is not ``"GCRS"``.

        Units/frame: km, km/s, GCRS.
        """
        with np.load(path, allow_pickle=False) as data:
            frame = str(data["frame"])
            if frame != "GCRS":
                raise ValueError(
                    f"CatalogEphemeris.load_npz: expected frame 'GCRS', got {frame!r}"
                )
            times = _timescale().tt_jd(
                np.asarray(data["time_whole"], dtype=np.float64),
                np.asarray(data["time_tt_fraction"], dtype=np.float64),
            )
            failures = [
                (int(nid), str(reason))
                for nid, reason in zip(
                    data["failure_norad_ids"], data["failure_reasons"]
                )
            ]
            return cls(
                norad_ids=np.asarray(data["norad_ids"], dtype=np.int64),
                position_km=np.ascontiguousarray(data["position_km"]),
                velocity_km_s=np.ascontiguousarray(data["velocity_km_s"]),
                times=times,
                failures=failures,
            )


def propagate_catalog(
    records: list[CatalogObject],
    start: datetime,
    hours: int,
    step_seconds: int,
    dtype: DTypeLike = np.float64,
) -> CatalogEphemeris:
    """Vectorised SGP4 propagation of a whole catalogue over one time grid.

    The many-object analogue of :func:`propagate_one`. Every record's SGP4
    model is stepped in a **single** ``sgp4.api.SatrecArray.sgp4`` call --
    there is no Python-level loop over objects -- and the resulting TEME
    states are rotated to **GCRS** in one
    :func:`prahari_orbital.frames.teme_to_gcrs_arrays` call. (The per-record
    ``Satrec.twoline2rv`` loop below is TLE *parsing* only; the propagation
    itself is the one vectorised call.)

    Args:
        records: catalogue objects. Only ``tle_line1`` / ``tle_line2`` /
            ``norad_id`` are read. A record whose TLE will not parse, or
            whose SGP4 propagation returns an error code or a non-finite
            value **at any step**, is dropped from the output arrays and
            listed in ``CatalogEphemeris.failures`` -- never zero-filled
            (a phantom object at the origin would appear to conjunct with
            everything).
        start: first sample instant. **Must be timezone-aware UTC** -- a
            naive datetime raises ``ValueError``.
        hours: total span of the grid, in hours (``>= 0``); both ends
            inclusive.
        step_seconds: spacing between samples, in seconds (``> 0``).
        dtype: floating dtype of the returned position/velocity arrays --
            ``numpy.float64`` (default) or ``numpy.float32``; anything else
            raises ``ValueError``. SGP4 and the frame rotation always run in
            float64; the cast to float32, if asked for, happens last and
            halves the array footprint for hand-off (worst-case ~1 m /
            ~1 mm/s representation error at LEO radii).

    Returns:
        :class:`CatalogEphemeris`. ``position_km`` / ``velocity_km_s`` have
        shape ``(n_ok, n_steps, 3)`` in **GCRS**, km and km/s, with
        ``n_ok = len(records) - len(failures)`` and
        ``n_steps = hours * 3600 // step_seconds + 1``.

    Raises:
        ValueError: ``start`` is naive; ``hours`` < 0; ``step_seconds`` <= 0;
            ``dtype`` is neither float64 nor float32; ``records`` is empty;
            or *every* record failed (an all-empty result is far more likely
            a caller bug than reality, so it raises rather than returns).

    Side effects:
        Writes one line to ``stderr`` on completion: object counts, step
        count, dtype, wall-clock time, and peak traced Python-heap memory
        (numpy buffers included) for the call.

    Units/frame: input ``start`` is UTC; output is km, km/s, **GCRS**.
    """
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError(
            "propagate_catalog: 'start' must be timezone-aware UTC, got a naive datetime"
        )
    if hours < 0:
        raise ValueError(f"propagate_catalog: 'hours' must be >= 0, got {hours}")
    if step_seconds <= 0:
        raise ValueError(
            f"propagate_catalog: 'step_seconds' must be > 0, got {step_seconds}"
        )
    out_dtype = np.dtype(dtype)
    if out_dtype not in (np.dtype(np.float64), np.dtype(np.float32)):
        raise ValueError(
            f"propagate_catalog: 'dtype' must be float64 or float32, got {out_dtype.name}"
        )
    if not records:
        raise ValueError("propagate_catalog: 'records' is empty")

    wall_start = time.perf_counter()
    tracemalloc.start()
    try:
        ts = _timescale()
        t0 = ts.from_datetime(start)
        n_steps = hours * 3600 // step_seconds + 1
        step_days = step_seconds / 86400.0
        # Same grid construction as propagate_one() / make_time_grid().
        times = ts.tt_jd(t0.tt + np.arange(n_steps, dtype=np.float64) * step_days)

        # TLE parsing only -- one Satrec per record. Unparseable lines are a
        # failure for that NORAD id, not an abort for the batch.
        satrecs: list[Satrec] = []
        kept_ids: list[int] = []
        failures: list[tuple[int, str]] = []
        for rec in records:
            try:
                satrecs.append(Satrec.twoline2rv(rec.tle_line1, rec.tle_line2))
            except (ValueError, RuntimeError) as exc:
                failures.append((rec.norad_id, f"TLE parse failed: {exc}"))
            else:
                kept_ids.append(rec.norad_id)

        if not satrecs:
            raise ValueError(
                f"propagate_catalog: none of {len(records)} record(s) had a "
                f"parseable TLE; first few failures: {failures[:5]}"
            )

        # The one vectorised propagation call. jd / fr are the UTC Julian
        # day split the same way skyfield.sgp4lib feeds SGP4 (whole day +
        # UT1 fraction minus UT1-UTC), so this matches propagate_one exactly.
        jd = np.ascontiguousarray(times.whole, dtype=np.float64)
        fr = np.ascontiguousarray(
            times.ut1_fraction - times.dut1 / DAY_S, dtype=np.float64
        )
        err, r_teme_km, v_teme_km_s = SatrecArray(satrecs).sgp4(jd, fr)
        # err: (n, n_steps) uint8 ; r_teme_km / v_teme_km_s: (n, n_steps, 3)
        # in TEME, km and km/s.

        bad_row = (err != 0).any(axis=1)
        bad_row |= ~np.isfinite(r_teme_km).all(axis=(1, 2))
        bad_row |= ~np.isfinite(v_teme_km_s).all(axis=(1, 2))

        for i in np.nonzero(bad_row)[0]:
            codes = sorted({int(c) for c in err[i] if c})
            reason = (
                f"SGP4 error code(s) {codes}" if codes else "non-finite SGP4 output"
            )
            failures.append((kept_ids[i], reason))

        good = ~bad_row
        if not good.any():
            raise ValueError(
                f"propagate_catalog: all {len(records)} record(s) failed to "
                f"propagate; first few: {failures[:5]}"
            )

        norad_ids = np.array(kept_ids, dtype=np.int64)[good]
        pos_gcrs_km, vel_gcrs_km_s = frames.teme_to_gcrs_arrays(
            r_teme_km[good], v_teme_km_s[good], times
        )

        result = CatalogEphemeris(
            norad_ids=norad_ids,
            position_km=np.ascontiguousarray(pos_gcrs_km, dtype=out_dtype),
            velocity_km_s=np.ascontiguousarray(vel_gcrs_km_s, dtype=out_dtype),
            times=times,
            failures=failures,
        )

        wall_s = time.perf_counter() - wall_start
        _current, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    print(
        f"[propagate_catalog] {result.norad_ids.size} ok / {len(result.failures)} "
        f"failed, {n_steps} steps x 3 axes, dtype={out_dtype.name}: "
        f"wall {wall_s:.3f}s, peak traced heap {peak_bytes / 1e6:.1f} MB",
        file=sys.stderr,
    )
    return result


def build_satellite(obj: CatalogObject) -> EarthSatellite:
    """Construct a Skyfield EarthSatellite from a CatalogObject's TLE lines.

    Args:
        obj: CatalogObject with valid tle_line1/tle_line2.

    Returns:
        skyfield.api.EarthSatellite ready for propagation.
    """
    raise NotImplementedError("TODO(orbital-core): EarthSatellite(obj.tle_line1, obj.tle_line2, obj.name, ts)")


def propagate(
    obj: CatalogObject,
    times: Time,
) -> StateVector:
    """Propagate a single object's SGP4 elements to the given time(s).

    Args:
        obj: CatalogObject with valid TLE lines.
        times: Skyfield Time, scalar or vector (shape (N,)) of evaluation instants.

    Returns:
        StateVector in frame "GCRS" (this function performs the TEME->GCRS
        conversion internally via frames.teme_to_gcrs before returning —
        callers never see a raw TEME vector out of this module).
        position_km/velocity_km_s shape matches `times`: (3,) for scalar,
        (N, 3) for vector input.

    Raises:
        ValueError: if SGP4 reports a propagation error code (e.g. decayed orbit).

    Units: km, km/s, GCRS frame (~J2000).
    """
    raise NotImplementedError("TODO(orbital-core): sat.at(times) -> .position, .velocity, then frames.teme_to_gcrs")


def propagate_many(
    objects: list[CatalogObject],
    times: Time,
) -> dict[int, StateVector]:
    """Propagate a batch of objects to the same time grid, vectorised per object.

    Thin fan-out over `propagate`; exists so screen.py and filters.py have a
    single call site instead of a Python-level loop scattered across callers.

    Args:
        objects: CatalogObjects to propagate.
        times: shared Skyfield Time vector, shape (N,).

    Returns:
        dict keyed by norad_id -> StateVector (frame "GCRS", shape (N, 3)).
        Objects that raise during propagation are omitted, not re-raised;
        see propagate() Raises for why an individual object can fail.
    """
    raise NotImplementedError("TODO(orbital-core): {obj.norad_id: propagate(obj, times) for obj in objects}, skip failures")


def make_time_grid(start: Time, hours: float, step_seconds: float) -> Time:
    """Build an evenly-spaced Skyfield Time vector for propagation.

    Args:
        start: grid start instant.
        hours: total span, hours (e.g. 72 for the standard screening window).
        step_seconds: spacing between samples, seconds (e.g. 60 for the coarse
            pass, 1 for screen.py's fine re-propagation of survivors).

    Returns:
        Skyfield Time, shape (N,), N = floor(hours * 3600 / step_seconds) + 1.
    """
    n_steps = int(np.floor(hours * 3600.0 / step_seconds)) + 1
    raise NotImplementedError(f"TODO(orbital-core): ts.tt_jd(start.tt + arange({n_steps}) * step_seconds / 86400)")
