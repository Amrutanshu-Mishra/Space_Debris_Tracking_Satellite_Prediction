# 05 — Dashboard

Owns the event table, filters, drill-down, catalogue status display, and
alert list — the surface a judge or an operator actually looks at. Builds
against the mock API from Day 1; the mock data source is already fully
working, so there's no reason to wait on any other workstream to start.

## You own

- `web/src/views/Dashboard.tsx`
- `web/src/views/EventDetail.tsx`'s page layout (the non-`TODO(visualisation)`
  parts — coordinate with workstream 4 on the geometry section)
- `web/src/components/NavBar.tsx` and any new shared layout components

## Do not edit

- `web/src/api/` — frozen typed client. If the dashboard needs a filter or
  field the API doesn't expose, that's a workstream 3 conversation.
- `web/src/views/OrbitView.tsx` — workstream 4's file.
- `services/orbital/`, `services/api/` — not yours; you consume their API.

## Contract you consume

`GET /catalog/status` → `CatalogStatus`, `GET /conjunctions?...` →
`Page<ConjunctionEvent>`, both typed in `web/src/api/client.ts` /
`web/src/api/types/`. Worked example (one event from
`contracts/fixtures/conjunctions.sample.json`):

```json
{
  "event_id": "9f2c1a7e-3b44-4c81-9e0d-5a1f8b2c6d90",
  "primary": { "norad_id": 25544, "name": "ISS (ZARYA)" },
  "secondary": { "norad_id": 47423, "name": "COSMOS 2251 DEB" },
  "tca": "2026-08-27T04:17:33Z",
  "miss_distance_km": 0.412,
  "relative_velocity_km_s": 13.87,
  "risk_score": 0.83,
  "risk_tier": "RED",
  "confidence": 0.61,
  "confidence_note": "Secondary TLE epoch is 68 h old and perigee is below 500 km; drag uncertainty elevated.",
  "max_epoch_age_hours": 68.4
}
```

**`risk_score`/`confidence` are not the same axis** — see root README's
"Why we don't publish a probability of collision". Never label
`risk_score` as "probability" or "chance of collision" anywhere in the UI.

## Run just your slice

```bash
cd services/api && PRAHARI_DATA_SOURCE=mock uvicorn prahari_api.main:app --reload &
cd web && npm install && npm run dev
```

Visit `http://localhost:5173/` — 40 fixture events (~4 RED, ~12 AMBER, ~24
GREEN) are already there to design against.

## Day 1 / 2 / 3 targets

- **Day 1**: `Dashboard.tsx` replaces its placeholder table with a real
  sortable/filterable event table (tier filter, min-score filter — both
  already supported by `GET /conjunctions`) and a proper catalogue-status
  summary (funnel numbers, epoch-age p50/p90/max).
- **Day 2**: alert list / notification surface for new RED events arriving
  over `openEventStream` (`web/src/api/client.ts`); epoch-age indicators
  (visually distinguish stale-TLE events, tied to `confidence`/`confidence_note`).
- **Day 3**: `EventDetail.tsx`'s full layout — RTN breakdown, both objects'
  full `CatalogObject` detail, links back to `OrbitView` for each object.
  Feature freeze — polish and demo rehearsal only after today.

## Definition of done

Dashboard renders all 40 fixture events with working tier/score filters, a
live-updating alert list driven by `/api/v1/stream`, and every risk-facing
number is labelled as `risk_score`/`confidence` — never "probability" or
"Pc" — anywhere in the rendered UI or its source.

## Known traps

- **Stale-fixture drift.** Don't hardcode "4 RED events" or specific NORAD
  IDs into component logic — the fixture counts are a snapshot for
  design purposes, not a contract. Render whatever the API returns.
- **Mislabelling risk_score as a probability.** The single most likely way
  this project fails its own design constraint is a dashboard label that
  says "83% collision chance" instead of "risk score 0.83". Grep the diff
  for "probability", "chance", "Pc", "%" near `risk_score` before every PR.
- **WebSocket lifecycle.** `openEventStream` returns a raw `WebSocket`;
  clean it up in a `useEffect` cleanup function or you'll leak connections
  on every navigation away from the dashboard.
- **Pagination vs. "load everything".** `Page<T>` is real pagination
  (`limit`/`offset`) — don't quietly set `limit=10000` to avoid building
  pagination UI; the live catalogue will have far more events than the
  40-event fixture set.
