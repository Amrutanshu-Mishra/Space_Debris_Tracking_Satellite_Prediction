# 01 — Orbital core

Critical path. Everything downstream — filtering, screening, scoring, the
whole dashboard — is worthless if this is wrong. Frame confusion here
produces plausible-looking wrong answers that nobody downstream can catch,
so correctness on Day 1 matters more than speed.

## You own

- `services/orbital/prahari_orbital/ingest.py`
- `services/orbital/prahari_orbital/propagate.py`
- `services/orbital/prahari_orbital/frames.py`
- `services/orbital/tests/test_propagate.py`

## Do not edit

- `services/orbital/prahari_orbital/filters.py`, `screen.py`, `scoring.py` —
  workstream 2 (screening & scoring). They consume your `propagate()` and
  `frames` output; if their contract with you needs to change, talk to them
  before changing your function signatures.
- `services/orbital/prahari_orbital/models.py` — generated from
  `contracts/schemas/`. If you need a new field on `CatalogObject`, propose
  a schema change in `contracts/schemas/object.schema.json` and regenerate
  (`make seed`), don't hand-edit `models.py`.
- `services/api/`, `services/worker/`, `web/` — not yours; they import you.

## Contract you consume / produce

You consume raw CelesTrak text and TLE lines. You produce
`CatalogObject` (from `contracts/schemas/object.schema.json`):

```json
{
  "norad_id": 25544,
  "name": "ISS (ZARYA)",
  "tle_line1": "1 25544U 98067A   26236.55742...",
  "tle_line2": "2 25544  51.6416 247.4627 000...",
  "epoch": "2026-08-24T13:22:41Z",
  "epoch_age_hours": 41.2,
  "object_type": "PAYLOAD",
  "rcs_size": "LARGE",
  "radius_m": 55.0,
  "perigee_km": 413.2,
  "apogee_km": 421.8,
  "inclination_deg": 51.64
}
```

`propagate()` produces a `frames.StateVector` in frame `"GCRS"` — never
`"TEME"` — for anything downstream to consume. See `frames.py`'s module
docstring for the full frame reference (TEME/GCRS/ITRF).

## Run just your slice

```bash
cd services/orbital
pip install -e ".[dev]"
pytest -q                      # tests are skip-marked until you implement
python -c "
from prahari_orbital.ingest import RCS_RADIUS_LOOKUP_M
print(RCS_RADIUS_LOOKUP_M)
"
```

No API, worker, database, or frontend needs to be running.

## Day 1 / 2 / 3 targets

- **Day 1**: `propagate()` implemented; `test_propagate.py`'s ISS test
  (currently `@pytest.mark.skip`) passes with a real published reference
  position, error < 1 km. Remove the skip marker once it passes.
- **Day 2**: `ingest.py` fully implemented — real CelesTrak fetch, TLE
  validation with checksum, `build_catalog_objects` producing correct
  perigee/apogee/inclination for a known batch of objects.
- **Day 3**: `propagate_many` performance-acceptable for ~30k objects on
  the coarse time grid (workstream 2 needs this to hit their own targets);
  feature freeze — no new functions after today, only bug fixes.

## Definition of done

`services/orbital/tests/test_propagate.py::test_iss_position_matches_published_ephemeris`
passes with a real (not self-referential) reference position, and
`test_propagate_output_is_gcrs_not_teme` passes.

## Known traps

- **Frame confusion.** SGP4 outputs TEME. If you skip `frames.teme_to_gcrs`
  anywhere, or hand-roll a rotation instead of calling Skyfield, you'll get
  positions that are off by a plausible-looking few kilometres — not
  obviously wrong, so it won't get caught by a manual sanity check. Delegate
  every frame conversion to Skyfield, no exceptions.
- **TLE checksum silently wrong.** A malformed TLE that passes basic parsing
  but fails checksum validation should be dropped, not propagated — SGP4
  will often still "succeed" on bad elements and produce garbage silently.
- **Epoch age vs. "now".** `epoch_age_hours` must be computed relative to
  the screening run's timestamp, not import time or a hardcoded value — a
  stale hardcoded "now" will quietly make every confidence score wrong.
- **Decayed/deep-space objects.** SGP4 can return an error code for objects
  whose orbit has decayed. `propagate_many` must skip these, not crash the
  whole batch.
