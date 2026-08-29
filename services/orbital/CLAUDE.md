# CLAUDE.md — standing rules for `services/orbital/`

Operational guidance for an agent working in this directory. The root
`../../CLAUDE.md` still applies on top of this; where they overlap, the
stricter rule wins. This directory is the **orbital core**: TLE ingestion,
SGP4 propagation, coordinate frames, conjunction filtering, pair screening,
and risk scoring.

## Scope — what may and may not be written here

**May write / modify:**

- `prahari_orbital/ingest.py` — CelesTrak fetch, TLE parse, validation.
- `prahari_orbital/propagate.py` — SGP4 wrapper, TLE → state-vector series.
- `prahari_orbital/frames.py` — all coordinate-frame conversions.
- `prahari_orbital/filters.py` — coarse conjunction filtering.
- `prahari_orbital/screen.py` — pair screening / fine TCA search.
- `prahari_orbital/scoring.py` — risk score, confidence, tiers.
- `tests/` — the orbital test suite (`test_propagate.py`, `test_ingest.py`,
  `test_frames.py`, `test_filters.py`, `test_screen.py`, `test_scoring.py`,
  and new ones alongside them).
- `tools/` — small standalone scripts (fetch a TLE, dump an ephemeris,
  eyeball a frame conversion). Not imported by the library.

**Must NOT write or edit — these belong to other people:**

- `prahari_orbital/models.py` — generated from `contracts/schemas/`,
  never hand-edited (see root `CLAUDE.md`).
- Anything under `services/api/`, `services/worker/`, `web/`.

If asked to implement API routes, database models, or frontend code:
**refuse and say who owns it.** API and DB models are workstream 3
(`docs/team/03-backend-data.md`); the frontend is a separate workstream.
Those consume this package's propagation, screening, and scoring output; if
a contract between us needs to change, that is a conversation with those
owners, not a unilateral signature change here.

### `Ephemeris` (ours) vs `StateVector` (the shared seam)

`propagate.Ephemeris`, returned by `propagate_one(obj, start, hours,
step_seconds)`, is **this workstream's internal** single-object trajectory
type — not a frozen contract, not in `models.py`. It is built from and holds
a frozen-contract `CatalogObject` (read via `tle_line1` / `tle_line2` — the
contract field names, not the ingest-internal `TLERecord.line1`). Its
accessors (`.gcrs()`, `.itrf()`, `.subpoint()`, `.altitude_km()`) delegate to
`frames.py`. Frame name is **`GCRS`** everywhere, per the root CLAUDE.md —
never `GCRF`, even though Skyfield's `satellite.at()` docs say "GCRF".

The `CatalogObject -> StateVector` functions in `propagate.py` (`propagate`,
`propagate_many`, `make_time_grid`, `build_satellite`) and the
`StateVector`-based converters in `frames.py` (`teme_to_gcrs`, `gcrs_to_itrf`,
`itrf_to_lat_lon_alt`, `rtn_basis`) are the **seam with workstream 2**
(`filters.py`, `screen.py`). Leave their signatures alone. If `Ephemeris` and
`StateVector` should converge, that is a conversation with the screening
owner, not a unilateral edit here.

## Screening and scoring

- **`contracts/schemas/conjunction.schema.json` is frozen.** Scoring output
  must match it exactly — field names, types, nesting. If the schema
  genuinely needs a new field, change the schema first (see
  `contracts/README.md`) in the same change as the code that depends on it;
  never hand-edit the generated models.
- **There is no probability-of-collision field, and there never will be.**
  Public TLEs carry no covariance, so a true Pc is not derivable from this
  data. Never add such a field, never name anything `pc`, and never let a
  docstring, comment, or string literal imply the risk score is a
  probability. (This restates the root `CLAUDE.md` non-negotiable; it now
  applies with full force to `scoring.py`.)
- **The screening threshold is 10 km.** Any pair whose minimum separation
  over the propagation window falls below 10 km is a candidate conjunction
  event and is carried forward to scoring. Pairs that never come within
  10 km are dropped.

## Units and frames — the most important rules in the project

- **Distances in kilometres. Velocities in km/s. Times are timezone-aware
  UTC `datetime` objects (or Skyfield `Time`).** Never metres, never naive
  datetimes, never mix. A silent metre/kilometre slip here fabricates or
  hides a conjunction and nothing downstream can catch it.
- SGP4 natively emits position/velocity in **TEME** (True Equator, Mean
  Equinox). TEME is inertial-ish but is **not** GCRS/J2000 and **not**
  ITRF/ECEF. Do not treat it as either.
- The canonical output frame for everything downstream is **GCRS**,
  obtained via Skyfield's `.at()`, not by hand-rolled rotation. "GCRS" is
  Skyfield's own term and the term used in the frozen contract, so it is
  the term used everywhere in this package. (GCRF is the frame
  *realization* of the GCRS *system*; the distinction is far below our
  error budget and we do not track it.)
- **The string `"GCRS"` in `contracts/schemas/object.schema.json` and the
  `docs/team/` files is frozen. Never "correct" it to "GCRF"** — in a
  schema, a docstring, a `StateVector.frame` value, a test, or anywhere
  else. That rename would break the contract for zero physical gain.
- **All frame conversion happens in `frames.py` and nowhere else.** No
  inline TEME→GCRS, GCRS→ITRF, or ECEF math in `ingest.py`, `propagate.py`,
  tests, or tools. `propagate()` calls into `frames.py` and returns GCRS;
  callers never see a raw TEME vector leave this package.
- **Every public function's docstring states, explicitly: input units,
  output units, and output coordinate frame.** No exceptions, including
  helpers that "obviously" don't convert anything.

## No async in this package

`ingest.py` — and every module here — is pure synchronous library code.
It is called from a Celery worker, which has no event loop. Do not
introduce `async def`, `await`, `httpx.AsyncClient`, or an asyncio
dependency. HTTP is done with `requests` (blocking).

## Correctness

- **Never write a test that compares our output to our own output.** Every
  test asserts against an external reference (a published SGP4 verification
  vector, JPL Horizons, an independent ephemeris) or an independently-known
  physical fact (orbital period from mean motion, altitude band, energy
  sign, frame-rotation orthogonality). A self-comparison is not a test.
- **Never silently zero-fill or swallow a numerical failure.** SGP4 error
  codes, non-finite results, and parse failures are collected and reported
  **keyed by NORAD ID**, then surfaced to the caller. One bad TLE in a 30k
  feed must not abort the ingest, and must not vanish either.
- **If you are unsure whether something is numerically correct, say so
  plainly.** A docstring or comment stating "this frame handling is not yet
  verified against an external source" is correct behaviour. Confident code
  over an unverified conversion is not.

## Style

- Type hints on everything. `mypy --strict` must pass.
- Pydantic v2 for data models. numpy for numeric arrays.
- No premature optimisation. Correct first; fast later, and only toward a
  stated performance target, with the before/after numbers written down.

## Running just this slice

```bash
cd services/orbital
pip install -e ".[dev]"      # or: pip install -r requirements.txt
pytest -q                    # tests are skip-marked until implemented
```
