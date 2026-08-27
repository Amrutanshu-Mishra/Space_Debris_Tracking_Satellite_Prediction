# 03 — Backend & data

Ships the mock-backed API on Day 1 so workstreams 4 and 5 are never
blocked. Owns the boundary between "the orbital pipeline's output" and
"what the frontend can fetch" — including the one part of this skeleton
that must already work: mock mode.

## You own

- `services/api/` (all of it: `prahari_api/config.py`, `data/`, `routers/`,
  `main.py`, `schemas.py`, `tests/`)
- `services/worker/` (all of it)
- `docker-compose.yml`, `.env.example` (shared with workstream 6 — coordinate
  before changing service definitions)

## Do not edit

- `services/orbital/` — workstreams 1 and 2. You import
  `prahari_orbital` (via `services/api/prahari_api/data/live.py` and
  `services/worker/prahari_worker/tasks.py`); if their functions don't do
  what you need, ask them to change it, don't reimplement pipeline logic
  in `live.py` or `tasks.py`.
- `contracts/schemas/` — frozen. If an endpoint needs a field that isn't in
  the schema, that's a schema-change conversation, not a backend-only fix.
- `web/` — not yours; it's your consumer.

## Contract you consume / produce

You consume `CatalogObject`/`ConjunctionEvent`/`CatalogStatus` (from
`prahari_orbital.models`, generated from `contracts/schemas/`) and produce
the frozen API surface:

```
GET  /api/v1/health
GET  /api/v1/catalog/status
GET  /api/v1/objects?q=&type=&limit=&offset=
GET  /api/v1/objects/{norad_id}
GET  /api/v1/conjunctions?tier=&since=&until=&min_score=&limit=&offset=
GET  /api/v1/conjunctions/{event_id}
GET  /api/v1/conjunctions/{event_id}/geometry
GET  /api/v1/objects/{norad_id}/track?hours=
WS   /api/v1/stream
```

List endpoints return `{"items": [...], "total": int, "limit": int, "offset": int}`
(`prahari_api.schemas.Page`). `/stream` sends
`{"type": "snapshot" | "event", "data": ...}`.

## Run just your slice

```bash
cd services/api
pip install -e ".[dev]"
PRAHARI_DATA_SOURCE=mock uvicorn prahari_api.main:app --reload
# in another shell:
pytest -q          # 11 tests, all real, all passing against contracts/fixtures
curl localhost:8000/api/v1/health
```

No database, Redis, worker, or frontend needs to be running — mock mode
serves everything from `contracts/fixtures/` in memory.

## Day 1 / 2 / 3 targets

- **Day 1**: done already in the skeleton — `PRAHARI_DATA_SOURCE=mock` serves
  every endpoint against fixtures; `pytest -q` passes 11/11. Your Day 1 job
  is to keep it that way while you start on `live.py`/Postgres/Celery wiring.
- **Day 2**: Postgres schema + SQLAlchemy models for `objects` and
  `conjunctions` tables; `services/worker/prahari_worker/tasks.py`'s
  `refresh_catalog` and `run_screening` implemented against workstream 1/2's
  functions once those land, writing to Postgres.
  `services/api/prahari_api/data/live.py` reads from Postgres instead of
  raising `NotImplementedError`.
- **Day 3**: `/stream`'s live mode subscribes to the worker's Redis pub/sub
  channel (see `stream.py`'s `TODO`); full `docker-compose up` boots
  `PRAHARI_DATA_SOURCE=live` end to end against a real (if small) catalogue.
  Feature freeze — no new endpoints after today.

## Definition of done

`services/api/tests/test_mock_api.py` passes (already does), plus an
equivalent live-mode test suite you write once `live.py` is implemented,
run against a docker-composed Postgres+Redis.

## Known traps

- **Don't let mock mode regress.** Every router must go through
  `Depends(get_data_source)` — never import `MockDataSource` or
  `LiveDataSource` directly in a router. If you add a new endpoint, add it
  to the `DataSource` protocol in `data/base.py` first, implement both
  `mock.py` and `live.py` (the latter can raise `NotImplementedError` with
  a `TODO`), then wire the router.
- **Silent NotImplementedError swallowing.** `live.py`'s stubs must keep
  raising, loudly, until implemented. Don't wrap them in a try/except that
  returns empty data "to be safe" — that hides real bugs and produces a
  demo that looks like it's working in live mode when it isn't.
- **Migrating schema drift.** If you add a Postgres column that mirrors a
  contract field, keep the column name identical to the JSON field name.
  A silent rename here is exactly the kind of drift `contracts/README.md`'s
  freeze rule exists to prevent.
- **CORS in docker-compose vs. local dev.** `API_CORS_ORIGINS` defaults to
  `http://localhost:5173`; if workstream 4/5 run the frontend on a different
  port or host, update `.env`, don't hardcode a second origin into
  `main.py`.
