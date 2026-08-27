# 04 — Visualisation

Owns orbit and ground-track rendering, and the geometry view around a
conjunction's TCA. You never need the real orbital pipeline running —
`GET /objects/{norad_id}/track` and `GET /conjunctions/{event_id}/geometry`
already return real-shaped (if synthesised) data in mock mode from Day 1.

## You own

- `web/src/views/OrbitView.tsx`
- The geometry-plot portion of `web/src/views/EventDetail.tsx` (the
  `TODO(visualisation)` block — coordinate with workstream 5 on the rest of
  that file's layout, since they own the page shell)
- Any new components under `web/src/components/` for orbit/geometry
  rendering (e.g. a `TrackMap.tsx`, `GeometryPlot.tsx`)

## Do not edit

- `web/src/api/` — the typed client and generated types are frozen contract
  surface. If a track/geometry response is missing a field you need, that's
  a `contracts/schemas/` conversation (via workstream 3), not a client hack.
- `web/src/views/Dashboard.tsx` — workstream 5's file, beyond the parts they
  ask you to help with.
- `services/orbital/`, `services/api/` — not yours; you consume their API.

## Contract you consume

`GET /objects/{norad_id}/track?hours=` → `TrackPoint[]`:

```json
{ "t": "2026-08-26T09:05:00Z", "lat_deg": 12.34, "lon_deg": -45.67, "alt_km": 415.2 }
```

`GET /conjunctions/{event_id}/geometry` → `GeometrySample[]`:

```json
{ "t": "2026-08-27T04:16:33Z", "separation_km": 0.62 }
```

Both types live in `web/src/api/client.ts`. In mock mode these are
synthesised (see `services/api/prahari_api/data/mock.py`'s
`get_object_track`/`get_conjunction_geometry` docstrings) — good enough
shape to build against, not physically accurate; don't rely on the specific
curve shape for anything beyond "does my chart render."

## Run just your slice

```bash
cd services/api && PRAHARI_DATA_SOURCE=mock uvicorn prahari_api.main:app --reload &
cd web && npm install && npm run dev
```

Visit `http://localhost:5173/orbit/25544` or `.../orbit` (defaults to ISS).

## Day 1 / 2 / 3 targets

- **Day 1**: `OrbitView.tsx` renders `TrackPoint[]` as an actual map/globe
  (Plotly scattergeo, or Cesium if time allows) instead of the placeholder
  table currently in the skeleton.
- **Day 2**: `EventDetail.tsx`'s geometry section renders `GeometrySample[]`
  as a separation-vs-time chart, with the TCA instant clearly marked and
  the RTN components (`radial_km`/`in_track_km`/`cross_track_km`) shown
  alongside, not just total separation.
- **Day 3**: both views handle the real (not synthesised) shapes once
  `PRAHARI_DATA_SOURCE=live` lands — verify against workstream 3 before
  Day 3 ends. Feature freeze — polish only after today.

## Definition of done

`OrbitView` and `EventDetail`'s geometry section render without console
errors against both `PRAHARI_DATA_SOURCE=mock` and (once available) `live`,
for at least one object with a real close approach in the fixture data
(e.g. NORAD 25544 vs. a debris object from `contracts/fixtures/conjunctions.sample.json`).

## Known traps

- **Stale-fixture drift.** If you hardcode assumptions from the current
  `contracts/fixtures/*.sample.json` (e.g. "geometry always has 13
  samples"), your component will break the moment fixtures regenerate or
  live mode returns a different sample count. Render whatever length the
  API gives you.
- **Synthesised ≠ physical.** Mock mode's track/geometry data is a plausible
  shape, not real orbital mechanics — don't build a feature (e.g. "detect
  the orbit is circular") that depends on subtle physical correctness of
  mock data; it'll break the moment live mode's real propagation replaces it.
- **WebSocket reconnection.** If you build anything that consumes
  `openEventStream` (e.g. a live orbit-track updater), handle `onclose`/
  reconnect — the mock server's replay loop and a real Redis-backed stream
  will both drop connections occasionally.
