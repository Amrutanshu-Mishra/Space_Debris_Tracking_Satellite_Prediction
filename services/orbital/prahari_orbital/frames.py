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
from skyfield.framelib import itrs
from skyfield.positionlib import Geocentric
from skyfield.sgp4lib import TEME
from skyfield.timelib import Time
from skyfield.toposlib import wgs84
from skyfield.units import Distance


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


# --------------------------------------------------------------------------- #
# Ephemeris-path conversions.                                                 #
#                                                                             #
# propagate.Ephemeris (workstream-1 internal type) stores a GCRS position     #
# straight from Skyfield's EarthSatellite.at(); its accessor methods call     #
# the functions below, so this module stays the single place any frame-typed  #
# value in the pipeline originates. Inputs: a GCRS position array plus the    #
# matching Skyfield Time. Outputs: plain ndarrays -- propagate.py never has   #
# to import Skyfield's frame internals.                                       #
#                                                                             #
# The StateVector-based functions above are a separate seam (filters.py /     #
# screen.py, workstream 2) and are deliberately left untouched.               #
# --------------------------------------------------------------------------- #


def _gcrs_xyz_for_skyfield(position_km_gcrs: np.ndarray) -> np.ndarray:
    """(N, 3) or (3,) km GCRS -> (3, N) or (3,) km, the layout Skyfield wants."""
    arr = np.asarray(position_km_gcrs, dtype=np.float64)
    if arr.ndim == 1 and arr.shape == (3,):
        return arr
    if arr.ndim == 2 and arr.shape[1] == 3:
        return np.ascontiguousarray(arr.T)
    raise ValueError(
        f"position_km_gcrs must be shape (N, 3) or (3,), got {arr.shape}"
    )


def _geocentric_gcrs(position_km_gcrs: np.ndarray, t: Time) -> Geocentric:
    """Reconstitute a Skyfield Geocentric (GCRS) position from a km array + its Time.

    The single spot that rebuilds a Skyfield position object from raw numbers;
    every Ephemeris-path conversion below funnels through it.

    Units: km in. Frame: GCRS in, GCRS out (Skyfield ``center == 399``).
    """
    xyz = _gcrs_xyz_for_skyfield(position_km_gcrs)
    return Geocentric(Distance(km=xyz).au, t=t)


def gcrs_position_km(position_km_gcrs: np.ndarray) -> np.ndarray:
    """Validate and return a GCRS position array (no rotation applied).

    Skyfield's ``EarthSatellite.at()`` already yields a GCRS-referred
    geocentric position, so there is nothing to convert. This function exists
    so ``propagate.Ephemeris.gcrs()`` still obtains its array *through*
    ``frames`` -- keeping this module the sole origin of frame-typed values.

    Args:
        position_km_gcrs: ndarray, shape (N, 3) or (3,), kilometres, GCRS.

    Returns:
        float64 C-contiguous ndarray, same shape, kilometres, GCRS frame.

    Units: km in, km out. Frame: GCRS in, GCRS out.
    """
    arr = np.ascontiguousarray(position_km_gcrs, dtype=np.float64)
    if arr.shape[-1] != 3:
        raise ValueError(f"position_km_gcrs last axis must be 3, got {arr.shape}")
    return arr


def gcrs_to_itrf_position_km(position_km_gcrs: np.ndarray, t: Time) -> np.ndarray:
    """Rotate a GCRS position into ITRF (Earth-fixed / ECEF), via Skyfield.

    Args:
        position_km_gcrs: ndarray, shape (N, 3) or (3,), kilometres, GCRS.
        t: Skyfield ``Time``, shape (N,) or scalar, aligned element-for-element
            with ``position_km_gcrs`` -- each sample is rotated with its own
            Earth-orientation parameters.

    Returns:
        float64 ndarray, same shape as ``position_km_gcrs``, kilometres, ITRF.

    Units: km in, km out (rotation only, no unit change).
    Frame: GCRS in, ITRF out. Skyfield applies precession, nutation, sidereal
    Earth rotation (with UT1-UTC) and polar motion.
    """
    xyz = _geocentric_gcrs(position_km_gcrs, t).frame_xyz(itrs).km
    out = xyz.T if xyz.ndim == 2 else xyz
    return np.ascontiguousarray(out, dtype=np.float64)


def gcrs_to_geodetic(position_km_gcrs: np.ndarray, t: Time) -> np.ndarray:
    """Geodetic sub-satellite point (WGS84) of a GCRS position, via Skyfield.

    Args:
        position_km_gcrs: ndarray, shape (N, 3) or (3,), kilometres, GCRS.
        t: Skyfield ``Time``, shape (N,) or scalar, aligned with the position.

    Returns:
        float64 ndarray, shape (N, 3) or (3,): last-axis columns are
        ``[latitude_deg, longitude_deg, altitude_km]`` on the WGS84 ellipsoid.

    Units: km in; latitude/longitude out in degrees, altitude out in km above
    the WGS84 ellipsoid (ellipsoidal height, not height above a sphere).
    Frame: GCRS in; geodetic WGS84 out (Skyfield goes GCRS -> ITRF -> geodetic).
    """
    gp = wgs84.geographic_position_of(_geocentric_gcrs(position_km_gcrs, t))
    lat = np.asarray(gp.latitude.degrees, dtype=np.float64)
    lon = np.asarray(gp.longitude.degrees, dtype=np.float64)
    alt = np.asarray(gp.elevation.km, dtype=np.float64)
    return np.stack((lat, lon, alt), axis=-1)


def teme_to_gcrs_arrays(
    position_km_teme: np.ndarray,
    velocity_km_s_teme: np.ndarray,
    t: Time,
) -> tuple[np.ndarray, np.ndarray]:
    """Rotate stacked TEME state arrays into GCRS, via Skyfield.

    The vectorised, array-in/array-out companion to the (still-stubbed)
    ``StateVector``-based :func:`teme_to_gcrs`. Used by
    :func:`prahari_orbital.propagate.propagate_catalog`, whose
    ``sgp4.api.SatrecArray`` step emits TEME for a whole catalogue at once;
    nothing downstream of ``propagate`` may see a raw TEME vector, and this
    is the only place that particular rotation is done for the batch path.

    Args:
        position_km_teme: float64 ndarray, shape ``(n_obj, n_time, 3)``,
            kilometres, **TEME** frame. Axis ``-1`` is x/y/z; axis ``-2`` is
            time and must align element-for-element with ``t``.
        velocity_km_s_teme: float64 ndarray, same shape, km/s, **TEME**.
        t: Skyfield ``Time``, shape ``(n_time,)`` -- the instants of axis
            ``-2``.

    Returns:
        ``(position_km_gcrs, velocity_km_s_gcrs)``: float64 C-contiguous
        ndarrays, each the same shape as the corresponding input, in the
        **GCRS** frame. Rotation only -- units unchanged (km, km/s).

    Raises:
        ValueError: inputs are not matching ``(n_obj, n_time, 3)`` arrays.

    Units: km / km per second in and out. Frame: TEME in, GCRS out.

    The rotation is ``skyfield.sgp4lib.TEME.rotation_at(t)`` -- the GMST1982
    spin composed with precession/nutation to date,
    ``rot_z(theta_GMST - GAST) . M`` -- applied transposed, which is exactly
    what ``skyfield.sgp4lib.EarthSatellite._at`` does per satellite, here
    done for the whole stack in one ``einsum``. It is cross-checked
    bit-for-bit against ``EarthSatellite.at()`` in
    ``tests/test_propagate_catalog.py``. The GCRS-vs-GCRF distinction is far
    below the error budget and the project term is "GCRS"
    (see ``services/orbital/CLAUDE.md``).
    """
    pos_teme = np.ascontiguousarray(position_km_teme, dtype=np.float64)
    vel_teme = np.ascontiguousarray(velocity_km_s_teme, dtype=np.float64)
    if pos_teme.ndim != 3 or pos_teme.shape[-1] != 3 or vel_teme.shape != pos_teme.shape:
        raise ValueError(
            "teme_to_gcrs_arrays: expected matching (n_obj, n_time, 3) arrays, "
            f"got position {pos_teme.shape} and velocity {vel_teme.shape}"
        )

    # rotation_at(t) -> R with x_teme = R . x_icrs; we want x_gcrs = R^T . x_teme.
    # Indices: j = source axis (TEME), i = target axis (GCRS), k = time,
    # o = object. Using R[j, i, k] instead of a materialised transpose.
    rot_icrs_to_teme = np.asarray(TEME.rotation_at(t), dtype=np.float64)
    if rot_icrs_to_teme.ndim == 2:  # scalar Time -> (3, 3)
        pos_gcrs = np.einsum("ji,okj->oki", rot_icrs_to_teme, pos_teme)
        vel_gcrs = np.einsum("ji,okj->oki", rot_icrs_to_teme, vel_teme)
    else:  # vector Time -> (3, 3, n_time)
        pos_gcrs = np.einsum("jik,okj->oki", rot_icrs_to_teme, pos_teme)
        vel_gcrs = np.einsum("jik,okj->oki", rot_icrs_to_teme, vel_teme)
    return np.ascontiguousarray(pos_gcrs), np.ascontiguousarray(vel_gcrs)
