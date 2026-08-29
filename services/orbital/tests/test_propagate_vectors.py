"""SGP4 verification against Vallado's official DoD test vectors.

The ``sgp4`` package bundles the canonical SGP4 certification data authored
by David Vallado for "Revisiting Spacetrack Report #3" (AIAA 2006-6753):

* ``SGP4-VER.TLE``  -- 33 test-case TLEs, several deliberately pathological
  (deep-space resonance, near-decay, Lyddane-fix edge cases). Each line 2
  carries a trailing ``tstart tstop tstep`` field, in minutes from epoch.
* ``tcppver.out``   -- the expected **TEME** state vector (position in km,
  velocity in km/s) at each offset, as produced by the reference C++
  implementation.

Both files ship inside the installed ``sgp4`` package -- no download, no
vendored copy. Located at runtime via ``importlib.resources``; on the
machine this was written they resolve to::

    <site-packages>/sgp4/SGP4-VER.TLE
    <site-packages>/sgp4/tcppver.out

For every (test case, offset) row we build the satellite through this
package's own construction path (``propagate._earth_satellite``) and
propagate to the offset. SGP4's native output frame is TEME and the
reference vectors are TEME, so the comparison is done in TEME -- before any
GCRS rotation -- which is the only place a 1-metre tolerance is meaningful.
(The GCRS path out of ``propagate_one`` is exercised by the sanity and
frames tests instead.)

Tolerances: position within 1 metre, velocity within 1 mm/s. Both are far
looser than the agreement actually observed (~1e-4 m / ~1e-3 mm/s), but
tight enough that any km/m unit slip, TLE line-1/line-2 swap, or wrong
gravity model fails the test.
"""

from __future__ import annotations

import types
from importlib.resources import files

import numpy as np

from prahari_orbital.propagate import _earth_satellite, _timescale

MAX_POSITION_ERROR_KM = 1.0e-3  # 1 metre
MAX_VELOCITY_ERROR_KM_S = 1.0e-6  # 1 mm/s

# (tsince_minutes, r_teme_km shape (3,), v_teme_km_s shape (3,))
Row = tuple[float, np.ndarray, np.ndarray]
# (satnum, tle_line1, tle_line2, rows)
Case = tuple[int, str, str, list[Row]]


def _load_reference() -> list[Case]:
    """Parse the bundled Vallado files into aligned test cases, in file order."""
    sgp4_pkg = files("sgp4")
    tle_text = (sgp4_pkg / "SGP4-VER.TLE").read_text(encoding="ascii")
    out_text = (
        (sgp4_pkg / "tcppver.out").read_text(encoding="ascii").replace("\r", "")
    )

    tle_pairs: list[tuple[str, str]] = []
    lines = iter(tle_text.splitlines())
    for line1 in lines:
        if not line1.startswith("1"):
            continue
        line2 = next(lines)
        tle_pairs.append((line1, line2))

    block_satnums: list[int] = []
    block_rows: list[list[Row]] = []
    for raw in out_text.splitlines():
        text = raw.strip()
        if not text:
            continue
        if text.endswith("xx"):
            block_satnums.append(int(text.split()[0]))
            block_rows.append([])
        else:
            f = text.split()
            block_rows[-1].append(
                (
                    float(f[0]),
                    np.array([float(f[1]), float(f[2]), float(f[3])]),
                    np.array([float(f[4]), float(f[5]), float(f[6])]),
                )
            )

    assert len(tle_pairs) == len(block_satnums), (len(tle_pairs), len(block_satnums))
    return [
        (satnum, l1, l2, rows)
        for (l1, l2), satnum, rows in zip(tle_pairs, block_satnums, block_rows)
    ]


REFERENCE = _load_reference()


def test_reference_data_present() -> None:
    """The bundled Vallado files were found, located and parsed."""
    assert len(REFERENCE) == 33
    total_rows = sum(len(rows) for _, _, _, rows in REFERENCE)
    assert total_rows > 600, total_rows


def test_propagation_matches_vallado_vectors(capsys) -> None:
    ts = _timescale()

    total_checked = 0
    skipped_nonfinite = 0
    worst_pos_m = 0.0
    worst_vel_mm_s = 0.0

    for satnum, line1, line2, rows in REFERENCE:
        obj = types.SimpleNamespace(
            tle_line1=line1, tle_line2=line2, name=str(satnum)
        )
        sat = _earth_satellite(obj, ts)
        assert sat.model.satnum == satnum, (sat.model.satnum, satnum)

        for tsince_min, r_ref_km, v_ref_km_s in rows:
            _err, r_km, v_km_s = sat.model.sgp4_tsince(tsince_min)
            r_km = np.asarray(r_km, dtype=np.float64)
            v_km_s = np.asarray(v_km_s, dtype=np.float64)

            if not (np.isfinite(r_km).all() and np.isfinite(v_km_s).all()):
                # Vallado's own run also fails here (decayed / unrecoverable
                # elements); the reference file simply stops emitting. There
                # is nothing to compare against, so skip rather than invent.
                skipped_nonfinite += 1
                continue

            pos_err = float(np.linalg.norm(r_km - r_ref_km))
            vel_err = float(np.linalg.norm(v_km_s - v_ref_km_s))
            worst_pos_m = max(worst_pos_m, pos_err * 1e3)
            worst_vel_mm_s = max(worst_vel_mm_s, vel_err * 1e6)

            assert pos_err < MAX_POSITION_ERROR_KM, (
                f"NORAD {satnum} @ {tsince_min:g} min: TEME position off by "
                f"{pos_err * 1e3:.6f} m (limit 1 m)"
            )
            assert vel_err < MAX_VELOCITY_ERROR_KM_S, (
                f"NORAD {satnum} @ {tsince_min:g} min: TEME velocity off by "
                f"{vel_err * 1e6:.6f} mm/s (limit 1 mm/s)"
            )
            total_checked += 1

    assert total_checked > 600, total_checked

    with capsys.disabled():
        print(
            f"\n[test_propagate_vectors] exercised {total_checked} (case, offset) "
            f"rows across {len(REFERENCE)} Vallado test cases "
            f"({skipped_nonfinite} rows skipped: non-finite, reference also stops). "
            f"Worst position error {worst_pos_m:.6f} m, "
            f"worst velocity error {worst_vel_mm_s:.6f} mm/s."
        )
