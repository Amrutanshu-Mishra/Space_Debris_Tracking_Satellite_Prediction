"""All coordinate frame conversions live here, and only here.

SGP4 propagates in **TEME** (True Equator, Mean Equinox) — not J2000, not
ECEF/ITRS. Every other module in this package is forbidden from doing its
own frame math: hand-rolled TEME->ECEF or TEME->J2000 conversions produce
plausible-looking wrong answers (a few km of silent error is enough to hide
or fabricate a conjunction). All conversions are delegated to Skyfield,
which handles precession, nutation, polar motion, and UT1-UTC for us.

Frame reference:
    TEME  - True Equator, Mean Equinox. Native SGP4 output frame. Inertial-ish,
            but not a rigorous inertial frame (no precession/nutation applied).
    GCRS  - Geocentric Celestial Reference System, effectively J2000. The
            frame `propagate.py` should convert into immediately after SGP4,
            before any downstream geometry (filters, screening) touches it.
    ITRF  - International Terrestrial Reference Frame, i.e. ECEF. Used only
            for ground-track / lat-lon output (services/api track endpoint).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from skyfield.timelib import Time


@dataclass(frozen=True)
class StateVector:
    """Position and velocity at a single instant, in a single named frame.

    Attributes:
        position_km: shape (3,) or (N, 3), kilometres.
        velocity_km_s: shape (3,) or (N, 3), kilometres/second.
        frame: one of "TEME", "GCRS", "ITRF".
        time: Skyfield Time (scalar or vector, matching position_km's leading shape).
    """

    position_km: np.ndarray
    velocity_km_s: np.ndarray
    frame: str
    time: Time


def teme_to_gcrs(state: StateVector) -> StateVector:
    """Convert a TEME state vector to GCRS (~J2000), via Skyfield.

    Args:
        state: StateVector with frame == "TEME".

    Returns:
        StateVector with frame == "GCRS", same shape as input.

    Raises:
        ValueError: if state.frame != "TEME".

    Units: km, km/s in, km, km/s out. No unit conversion performed, only frame rotation.
    """
    raise NotImplementedError("TODO(orbital-core): implement via skyfield.sgp4lib TEME frame")


def gcrs_to_itrf(state: StateVector) -> StateVector:
    """Convert a GCRS state vector to ITRF (ECEF), via Skyfield.

    Used only for ground-track output; conjunction screening stays in GCRS.

    Args:
        state: StateVector with frame == "GCRS".

    Returns:
        StateVector with frame == "ITRF", same shape as input.

    Units: km, km/s in, km, km/s out.
    """
    raise NotImplementedError("TODO(orbital-core): implement via skyfield ITRS frame")


def itrf_to_lat_lon_alt(state: StateVector) -> np.ndarray:
    """Convert an ITRF position to geodetic latitude/longitude/altitude (WGS84).

    Args:
        state: StateVector with frame == "ITRF".

    Returns:
        ndarray shape (..., 3): [latitude_deg, longitude_deg, altitude_km], WGS84.
    """
    raise NotImplementedError("TODO(orbital-core): implement via skyfield.toposlib.wgs84.geographic_position_of")


def rtn_basis(state_gcrs: StateVector) -> np.ndarray:
    """Compute the Radial/In-track/Cross-track (RTN) rotation basis for an object.

    Used by screen.py to decompose the miss-distance vector into
    radial_km / in_track_km / cross_track_km for the conjunction contract.

    Args:
        state_gcrs: StateVector with frame == "GCRS", single instant (position_km shape (3,)).

    Returns:
        ndarray shape (3, 3): rows are unit vectors [R, T, N] in GCRS, such that
        a GCRS displacement vector `d` projects to RTN via `rtn_basis(state) @ d`.

    Units: dimensionless (unit vectors); no conversion of state itself.
    """
    raise NotImplementedError("TODO(orbital-core): R = pos/|pos|, N = pos x vel / |pos x vel|, T = N x R")
