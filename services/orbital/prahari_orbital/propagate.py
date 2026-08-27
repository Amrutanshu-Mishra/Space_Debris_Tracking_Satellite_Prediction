"""SGP4 wrapper: TLE -> position/velocity time series, vectorised.

Owns the boundary between "TLE mean elements" and "state vectors usable by
the rest of the pipeline". Emits TEME state vectors and immediately hands
them to frames.teme_to_gcrs — nothing downstream of this module should ever
see a raw TEME vector.
"""

from __future__ import annotations

import numpy as np
from skyfield.api import EarthSatellite, Time

from prahari_orbital.frames import StateVector
from prahari_orbital.models import CatalogObject


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
