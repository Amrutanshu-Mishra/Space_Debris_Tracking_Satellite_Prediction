# Architecture

See the root [README.md](../README.md) for the diagram, the funnel numbers,
and the Pc design decision. This document goes one level deeper on the
pieces that don't fit there.

## Why services/orbital is a pure library

`services/orbital/prahari_orbital` has no dependency on FastAPI, Celery, or
a database. It is imported by both `services/api` (for `live.py`'s
re-propagation of geometry/track endpoints) and `services/worker` (for the
scheduled ingest+screen pipeline). Keeping it framework-free means:

- it can be unit-tested with plain `pytest`, no app context needed;
- it can be profiled/optimised in isolation (the coarse filter is the
  performance-critical path — see `filters.py`);
- workstream 1 and 2 never need the API or worker running to iterate.

## Why frames.py is the only place that touches coordinate frames

SGP4 outputs TEME (True Equator, Mean Equinox), not J2000 and not ECEF.
Every other module in `prahari_orbital` treats frame conversion as Skyfield's
job, not its own — see `frames.py`'s module docstring for the full
rationale. This is the single most common way a project like this produces
plausible-looking wrong answers, so it gets one file, one set of functions,
and nothing else in the codebase is allowed to duplicate that logic.

## Why the coarse filter is three stages, not one

1. **Apogee/perigee band filter** — cheapest, uses only mean elements
   (no propagation needed). Prunes pairs whose altitude ranges can never
   overlap.
2. **Orbit-path geometry filter** — still uses only mean elements, prunes
   pairs whose orbital planes can't geometrically intersect within margin.
3. **KD-tree spatial filter** — needs propagated positions on a coarse time
   grid (e.g. 60 s step over the 72 h window), but only over the much
   smaller set that survived stages 1–2.

Doing the expensive step (propagation + KD-tree) last, over the smallest
possible set, is what makes the ~450M-pair problem tractable on a laptop.
See Hoots, Crawford & Roehrich (1984), *Celestial Mechanics* 33(2), 143–158,
cited in `filters.py`.

## Why mock/live is a data-source abstraction, not an if/else in every route

`services/api/prahari_api/data/base.py` defines the `DataSource` protocol.
`mock.py` (fully implemented, backed by `contracts/fixtures/`) and `live.py`
(stub, backed by Postgres via the worker's screening output) both implement
it. Routers depend only on `get_data_source()` — see `data/dependency.py` —
so `PRAHARI_DATA_SOURCE=mock|live` is a one-line environment flag, not a
scattered set of conditionals, and workstreams 4/5/6 can build the entire
frontend against real-shaped data before workstream 1/2's pipeline lands.

## Confidence, not just risk_score

`scoring.confidence_band` is a second, independent signal from
`risk_score`: it answers "how much should you trust this number", not "how
risky is this event". A RED event with low confidence (e.g. a 68-hour-old
TLE on a sub-500 km object) should read differently on the dashboard than a
RED event with high confidence — see `docs/team/05-dashboard.md`'s target
for surfacing `confidence_note` next to `risk_tier`, not hiding it behind a
tooltip.
