# 02 — Screening & scoring

Consumes orbital core's `propagate()` output. You own the part of the
pipeline that turns "450 million possible pairs" into "a ranked list of ~150
events a human should look at" — the coarse filter is the performance-
critical path of the entire system.

## You own

- `services/orbital/prahari_orbital/filters.py`
- `services/orbital/prahari_orbital/screen.py`
- `services/orbital/prahari_orbital/scoring.py`
- `services/orbital/tests/test_filters.py`
- `services/orbital/tests/test_scoring.py`

## Do not edit

- `services/orbital/prahari_orbital/ingest.py`, `propagate.py`, `frames.py`
  — workstream 1 (orbital core). You consume `propagate()` and
  `CatalogObject`; if you need something different from them, ask, don't
  change their code yourself.
- `contracts/schemas/conjunction.schema.json` — frozen. In particular:
  **never add a `probability_of_collision` field.** See root README, "Why
  we don't publish a probability of collision", and `scoring.compute_pc`'s
  docstring before touching anything Pc-adjacent.
- `services/api/`, `services/worker/`, `web/` — not yours.

## Contract you consume / produce

You consume `CatalogObject` (workstream 1's output) plus
`frames.StateVector` in frame `"GCRS"`. You produce `ConjunctionEvent`
(from `contracts/schemas/conjunction.schema.json`):

```json
{
  "event_id": "9f2c1a7e-3b44-4c81-9e0d-5a1f8b2c6d90",
  "primary": { "norad_id": 25544, "name": "ISS (ZARYA)" },
  "secondary": { "norad_id": 47423, "name": "COSMOS 2251 DEB" },
  "tca": "2026-08-27T04:17:33Z",
  "miss_distance_km": 0.412,
  "relative_velocity_km_s": 13.87,
  "radial_km": 0.115,
  "in_track_km": 0.382,
  "cross_track_km": 0.094,
  "combined_radius_m": 62.5,
  "risk_score": 0.83,
  "risk_tier": "RED",
  "confidence": 0.61,
  "confidence_note": "Secondary TLE epoch is 68 h old and perigee is below 500 km; drag uncertainty elevated.",
  "max_epoch_age_hours": 68.4,
  "screened_at": "2026-08-26T09:00:12Z"
}
```

## Run just your slice

Until `propagate()` lands, work against synthetic `StateVector`s you build
by hand — `test_filters.py` and `test_scoring.py` are written to run with
no dependency on a real orbital-core implementation:

```bash
cd services/orbital
pip install -e ".[dev]"
pytest tests/test_filters.py tests/test_scoring.py -q
```

`test_scoring.py`'s pure-function tests (`risk_score`, `risk_tier`,
`confidence_band`) need no propagation at all — start there.

## Day 1 / 2 / 3 targets

- **Day 1**: `risk_score`, `risk_tier`, `confidence_band` implemented and
  passing `test_scoring.py`'s monotonicity/boundary tests, using synthetic
  inputs (no dependency on orbital core landing yet).
- **Day 2**: `apogee_perigee_prefilter` and `orbit_path_filter` implemented
  and passing `test_filters.py`'s "never discard a true positive" tests
  against synthetic pairs. Once orbital core's `propagate_many` lands,
  wire up `spatial_kdtree_filter`.
- **Day 3**: `coarse_filter` end-to-end prunes >99.99% of a real ~200-object
  catalogue (fixtures-scale) in well under a second; `screen_pair`'s
  Brent root-find converges correctly on synthetic closing/opening
  brackets. Feature freeze — no new functions after today.

## Definition of done

`services/orbital/tests/test_filters.py::test_coarse_filter_prunes_more_than_99_99_percent`
passes, and `test_scoring.py`'s full suite (including
`test_compute_pc_is_disabled`, which already passes) passes.

## Known traps

- **O(n²) anywhere in the coarse filter.** The whole point of the three-
  stage design is to avoid ever materialising all N² pairs. If you find
  yourself writing a nested loop over the full object list inside
  `spatial_kdtree_filter`, you've broken the funnel — use `scipy.spatial.cKDTree`.
- **False negatives in the coarse filter are silent and catastrophic.** A
  discarded true positive means a real close approach is never screened and
  nobody is warned — there's no error, no crash, just a missing row. Err
  toward keeping pairs in `test_filters.py`; false positives are cheap
  (screen.py discards them), false negatives are not.
- **Brent's method needs a valid bracket.** `find_tca` requires
  `range_rate(search_start) < 0` and `range_rate(search_end) > 0`. If the
  coarse filter hands you a bracket that doesn't actually straddle the
  minimum, `find_tca` must raise, not silently return a wrong TCA.
- **Weight tuning without documentation.** `scoring.py`'s
  `MISS_DISTANCE_WEIGHT`/`RELATIVE_VELOCITY_WEIGHT` are heuristic. If you
  change them, update the constants' comments and `docs/architecture.md` —
  a judge may ask why these specific numbers.
