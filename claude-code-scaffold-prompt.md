# Claude Code scaffolding prompt — PRAHARI

Paste everything below the line into Claude Code in an empty directory.

---

You are scaffolding a 5-day hackathon prototype. Read this entire brief before writing any files.

## Project

**PRAHARI** — an open-source, self-hostable space situational awareness platform. It ingests the public satellite catalogue, propagates every object forward, screens all object pairs for close approaches (conjunctions), scores the risk, and serves a dashboard.

Built for Smart India Hackathon PS-04 (Space Debris Tracking & Satellite Collision Risk Prediction Dashboard), Space Technology theme, Software category. Six-person team, five days.

## The domain, in enough detail to build correctly

Objects in Low Earth Orbit move at ~7-8 km/s. Two objects passing close can have a closing speed of 10-14 km/s, so any impact is catastrophic and produces thousands of fragments. Operators need advance warning of close approaches so they can manoeuvre.

The pipeline:

1. **Ingest** — fetch TLE/GP data from CelesTrak (open, no auth, no rate limit). ~30,000 objects. Each TLE has an epoch timestamp; data ages badly, especially below 500 km where atmospheric drag dominates.
2. **Propagate** — run each object forward 72 hours using SGP4. SGP4 outputs positions in the **TEME** frame, not J2000 and not ECEF. Frame confusion produces plausible-looking wrong answers, so delegate all conversions to Skyfield rather than hand-rolling them.
3. **Coarse filter** — the crux. 30,000 objects means ~450 million pairs. Brute force is impossible. Use analytic prefilters (apogee/perigee: if A's perigee exceeds B's apogee by more than the threshold, the pair can never come close — discard; then orbit-path geometry filters) plus a KD-tree spatial index. Reference: Hoots, Crawford & Roehrich (1984), Celestial Mechanics 33(2), 143-158. This must prune >99.99% of pairs.
4. **Fine screen** — re-propagate survivors at 1-second resolution. Closest approach is where the relative range-rate crosses zero; root-find on it (Brent) to get exact TCA and miss distance.
5. **Risk score** — composite of miss distance, relative velocity, combined object radius, weighted by TLE epoch age. Emits a tier: GREEN / AMBER / RED.
6. **Serve** — REST API, dashboard, orbit visualisation, alerts.

### Non-negotiable design constraint

**Never emit a probability of collision (Pc).** Public TLEs carry no covariance, so a true Pc is not derivable from this data. The system emits a clearly-labelled composite `risk_score` plus a `confidence` value that degrades as TLE epoch age increases. Do not add a `probability_of_collision` field, do not name anything `pc`, and do not let any docstring or UI string imply the score is a probability. Leave the Pc computation as a documented pluggable interface for the case where covariance data becomes available.

## Hard constraints

- The live demo runs on **docker-compose**. Kubernetes manifests are written as a scalability artifact only — they are never on the demo path.
- Everything must run on a single 8-core laptop. No GPU, no HPC, no paid cloud service.
- Six people work in parallel from Day 1. Nobody may be blocked waiting for someone else's code.
- Feature freeze end of Day 3.

## What to build now

A **skeleton**, not an implementation. Every module gets its real file structure, real signatures, real docstrings, and a `NotImplementedError` or a trivially-correct stub. The one exception: the mock data layer must be fully working, so frontend and API people can build against real-shaped data on Day 1.

### 1. Frozen contracts (do this first, everything else depends on it)

Create `contracts/` containing JSON Schema files and matching fixture data. These shapes are frozen for the whole project — generate Pydantic models and TypeScript types **from** these, so they can never drift apart.

**`contracts/schemas/object.schema.json`** — a catalogue object:

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

`object_type` is one of `PAYLOAD | ROCKET_BODY | DEBRIS | UNKNOWN`. `rcs_size` is one of `SMALL | MEDIUM | LARGE | UNKNOWN`. `radius_m` is the assumed hard-body radius derived from `rcs_size` — document the lookup table you use, because a judge may ask.

**`contracts/schemas/conjunction.schema.json`** — a screened event:

```json
{
  "event_id": "9f2c1a7e-3b44-4c81-9e0d-5a1f8b2c6d90",
  "primary":   { "norad_id": 25544, "name": "ISS (ZARYA)" },
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

`risk_score` and `confidence` are both 0.0-1.0. `risk_tier` is `GREEN | AMBER | RED`. Note again: no probability field.

**`contracts/schemas/catalog_status.schema.json`** — ingest health:

```json
{
  "object_count": 29847,
  "last_refresh": "2026-08-26T06:00:00Z",
  "next_refresh": "2026-08-26T12:00:00Z",
  "source": "celestrak-gp-active",
  "epoch_age_hours": { "p50": 8.4, "p90": 31.2, "max": 212.7 },
  "screening_window_hours": 72,
  "last_screen_duration_s": 187.3,
  "pairs_considered": 445_419_281,
  "pairs_fine_screened": 11_204,
  "events_found": 143
}
```

**Fixtures:** `contracts/fixtures/objects.sample.json` (200 realistic objects — real NORAD IDs and plausible TLEs for well-known satellites, plus debris entries) and `contracts/fixtures/conjunctions.sample.json` (**40 events**, deliberately spread across tiers: ~4 RED, ~12 AMBER, rest GREEN, with a realistic spread of miss distances from 0.1 km to 20 km, relative velocities from 0.3 to 14.5 km/s, and epoch ages from 2 h to 200 h so the confidence display has something to show). These fixtures are what the frontend builds against for the first three days — make them good.

### 2. API surface (also frozen)

```
GET  /api/v1/health
GET  /api/v1/catalog/status
GET  /api/v1/objects?q=&type=&limit=&offset=
GET  /api/v1/objects/{norad_id}
GET  /api/v1/conjunctions?tier=&since=&until=&min_score=&limit=&offset=
GET  /api/v1/conjunctions/{event_id}
GET  /api/v1/conjunctions/{event_id}/geometry     -> position samples around TCA for plotting
GET  /api/v1/objects/{norad_id}/track?hours=      -> ground track / orbit path points
WS   /api/v1/stream                                -> new + updated events
```

Every endpoint must work against fixtures from Day 1, behind a `PRAHARI_DATA_SOURCE=mock|live` env flag. Default to `mock`.

### 3. Repository layout

```
prahari/
  README.md                  root: what it is, one-command start, architecture diagram
  CLAUDE.md                  guidance for future Claude Code sessions in this repo
  Makefile                   make up / make test / make lint / make seed
  docker-compose.yml         api, worker, db, redis, web — the demo path
  .env.example
  contracts/
    schemas/                 JSON Schema, source of truth
    fixtures/                sample data
    README.md                how to regenerate models from schemas; the freeze rule
  services/
    orbital/                 pure library, no web framework
      prahari_orbital/
        ingest.py            CelesTrak fetch + TLE parse + validate
        propagate.py         SGP4 wrapper, TEME->ECI, vectorised
        filters.py           apogee/perigee, orbit-path, KD-tree
        screen.py            fine screening, Brent root-find on range-rate
        scoring.py           risk score + confidence band
        frames.py            all coordinate conversions, one place
        models.py            Pydantic, generated from contracts/
      tests/
        test_propagate.py    regression vs published ISS ephemeris
        test_filters.py      prefilter must never discard a true positive
        test_scoring.py      monotonicity + boundary cases
    api/                     FastAPI app, thin, depends on orbital
    worker/                  Celery Beat: 6-hourly refresh, screening job
  web/                       React + TypeScript + Vite
    src/
      api/                   typed client generated from contracts/
      components/
      views/
        Dashboard.tsx
        EventDetail.tsx
        OrbitView.tsx
  k8s/                       Deployment, Service, HPA, CronJob — artifact only
  docs/
    architecture.md
    team/
      01-orbital-core.md
      02-screening-scoring.md
      03-backend-data.md
      04-visualisation.md
      05-dashboard.md
      06-integration-demo.md
  .github/workflows/ci.yml   lint, test, build
```

### 4. Six team READMEs

Write `docs/team/0N-*.md`, one per person. Each must contain, concretely:

- **You own** — the specific files and directories, listed by path.
- **Do not edit** — the paths owned by others. Say who to ask instead.
- **Contract you consume / produce** — the exact JSON shape, inline, with a worked example.
- **Run just your slice** — the precise commands to work without the rest of the stack up.
- **Day 1 / 2 / 3 targets** — concrete and checkable, e.g. "Day 1: SGP4 position for ISS matches published ephemeris within 1 km."
- **Definition of done** — the test that must pass.
- **Known traps** — the specific failure modes for that role (frame confusion for orbital core; O(n²) for screening; stale-fixture drift for frontend).

Role assignment:

1. **Orbital core** — ingest, propagate, frames. Critical path; everything downstream is worthless if this is wrong. Day 1 must end with a validated ISS position.
2. **Screening & scoring** — filters, fine screen, risk score. Consumes orbital core's output contract; works against synthetic ephemeris until it lands.
3. **Backend & data** — FastAPI, Postgres, Redis, Celery scheduling. Ships the mock-backed API on Day 1 so 4 and 5 are never blocked.
4. **Visualisation** — orbit and ground-track rendering, geometry view around TCA.
5. **Dashboard** — event table, filters, drill-down, catalogue status, epoch-age indicators, alert list.
6. **Integration, demo & QA** — compose wiring, CI, seed data, cross-service tests, the demo script, and the deck/video. This person also owns the feature-freeze call on Day 3.

### 5. Root README.md

Cover: what PRAHARI is (three sentences), the problem it solves, architecture diagram (Mermaid), the funnel numbers (~450M pairs → ~10⁴ fine-screened → ranked watchlist), one-command start, the six workstreams with links to their team docs, and an explicit **"Why we don't publish a probability of collision"** section — this is the project's headline design decision and it belongs where anyone opening the repo sees it.

## Style rules

- Type hints everywhere in Python; strict mode in TypeScript.
- Every stub carries a docstring stating its contract: inputs, outputs, units, coordinate frame. Units and frames in the signature or the docstring, always — this is where projects like this go wrong.
- No placeholder lorem text. If you don't know a value, use a realistic one and add a `# TODO(owner):` comment naming the role that owns it.
- Prefer boring, well-known libraries: `skyfield`, `sgp4`, `numpy`, `scipy`, `fastapi`, `pydantic`, `sqlalchemy`, `celery`, `redis`, `react`, `plotly`, `cesium`.

## Build order

1. `contracts/` — schemas and fixtures first, so nothing downstream can diverge.
2. Repo skeleton, Makefile, docker-compose, `.env.example`.
3. `services/orbital` stubs with full signatures and docstrings.
4. `services/api` serving fixtures end-to-end. **`make up` must produce a working mock API before you write a single line of frontend.**
5. `web/` shell with typed client and routed empty views.
6. `worker/`, `k8s/`, CI.
7. All seven READMEs (root + six team).

Then stop and print a summary of what exists, what is stubbed, and what each of the six people should do first.
