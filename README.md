# PRAHARI

PRAHARI is an open-source, self-hostable space situational awareness
platform. It ingests the public satellite catalogue, propagates every
tracked object forward in time, screens all object pairs for close
approaches, scores the risk of each one, and serves the result on a
dashboard.

Built for Smart India Hackathon PS-04 (Space Debris Tracking & Satellite
Collision Risk Prediction Dashboard), Space Technology theme, Software
category.

## The problem

Objects in Low Earth Orbit move at 7–8 km/s. Two objects passing close can
close at 10–14 km/s, so a collision is catastrophic and produces thousands
of new fragments — each of which becomes a new tracked hazard. Operators
need advance warning of close approaches so they can plan a manoeuvre.
PRAHARI automates the pipeline from "raw catalogue" to "ranked list of
approaches worth an operator's attention."

## Architecture

```mermaid
flowchart LR
    subgraph ingest["Ingest"]
        CT[CelesTrak GP/TLE feed]
    end

    subgraph orbital["services/orbital — pure library"]
        ING[ingest.py]
        PROP[propagate.py<br/>SGP4, TEME→GCRS]
        FILT[filters.py<br/>coarse filter]
        SCR[screen.py<br/>fine screen, Brent TCA]
        SCORE[scoring.py<br/>risk_score + confidence]
    end

    subgraph worker["services/worker"]
        BEAT[Celery Beat<br/>6-hourly schedule]
    end

    subgraph store["Postgres + Redis"]
        DB[(objects, conjunctions)]
        RDS[(pub/sub)]
    end

    subgraph api["services/api — FastAPI"]
        REST[REST /api/v1/*]
        WS[WS /api/v1/stream]
    end

    subgraph web["web — React + TypeScript"]
        DASH[Dashboard]
        EVT[EventDetail]
        ORB[OrbitView]
    end

    CT --> ING --> PROP --> FILT --> SCR --> SCORE --> DB
    BEAT --> ING
    DB --> REST
    SCORE -. publish .-> RDS -. forward .-> WS
    REST --> DASH & EVT & ORB
    WS --> DASH
```

## The funnel

~30,000 tracked objects means ~450 million possible pairs
(`pairs_considered`). Brute-force fine screening at that scale is
impossible on an 8-core laptop, so the coarse filter (apogee/perigee bands,
orbit-path geometry, then a KD-tree spatial pass — see
`services/orbital/prahari_orbital/filters.py`) has to prune more than
99.99% of pairs before anything reaches the expensive 1-second-resolution
fine screen:

```
~450,000,000 pairs considered
        │  apogee/perigee band filter
        │  orbit-path geometry filter
        │  KD-tree spatial filter
        ▼
     ~11,000 pairs fine-screened (1 s resolution, Brent root-find on TCA)
        ▼
       ~150 conjunction events (ranked, GREEN/AMBER/RED)
```

These numbers are exposed live via `GET /api/v1/catalog/status`
(`pairs_considered`, `pairs_fine_screened`, `events_found`).

## Why we don't publish a probability of collision

**PRAHARI never emits a probability of collision (Pc).** This is the
project's central design decision, and it's deliberate, not a shortcut.

A statistically valid Pc requires a covariance matrix for each object's
position uncertainty — the kind of data that comes from a Conjunction Data
Message (CDM) issued by the object's operator or a tracking authority.
Public TLEs from CelesTrak carry no such covariance. Any Pc computed from
TLEs alone is not a real probability; it's a number that *looks* like one
and will be trusted like one, which is worse than not having it.

Instead, PRAHARI emits two clearly-labelled numbers per event:

- **`risk_score`** (0–1): a composite heuristic combining miss distance,
  relative velocity, and combined object radius. It ranks events against
  each other; it is not a statement about the chance of impact.
- **`confidence`** (0–1): how much to trust the screening result, decaying
  as the older of the two TLE epochs ages — especially below 500 km, where
  atmospheric drag makes stale elements wrong fast.

The codebase enforces this: `contracts/schemas/conjunction.schema.json` has
no `probability_of_collision` field and rejects one via
`additionalProperties: false`; `scoring.compute_pc` exists only as a
disabled, documented interface for the day covariance data (e.g. real CDMs)
is available. See `CLAUDE.md` if you're extending this code and are
tempted to add one back.

## Run

The demo runs on Docker Compose. One command:

```bash
make demo
```

This builds two containers — `api` and `web` — starts them, waits for the
API health check, and prints the URL. Then open:

- **http://localhost:8080** — the operator console
- **http://localhost:8000/api/v1/health** — the API

`make up` does the same in the foreground with logs attached; `make down`
stops everything. There is no `.env` to copy and no database to provision —
the API runs in `mock` mode and serves the screened-events fixture from
`contracts/fixtures/`.

### Offline by design

The venue network is assumed hostile. Nothing in the running stack reaches
the internet:

- the screened-events JSON is **baked into the `api` image** (and also
  mounted from `contracts/` read-only) — nothing fetches CelesTrak at
  runtime;
- the web bundle carries its **own fonts, CSS, and the ground-track world
  outline** — no CDN, no Google Fonts, no map tile service;
- nginx in the `web` container **proxies `/api`** to the `api` service, so
  the browser only makes same-origin requests and CORS is a non-issue.

Prove it: `make demo-offline` builds the images, then brings the stack up on
a Compose network with `internal: true` — no route to the internet. If the
health checks pass there, nothing external is needed.

### Storage design

Persistence is **optional**. With no `DATABASE_URL` the API serves every
endpoint from the screened-events JSON held in memory — this is the demo
path, and it keeps working with no database container in sight. Set
`DATABASE_URL` (via `make demo-storage`, which also starts Postgres, Redis,
and a one-shot `loader`) and the same routes are served from Postgres by a
repository that returns the identical Pydantic models, so the routers can't
tell the difference.

**The tables don't mirror the wire format.** `contracts/schemas/` is the
shape the API *emits*; the schema is normalised for what the database is
good at:

- A `ConjunctionEvent` nests `primary` / `secondary` object refs. The
  `conjunctions` table stores `primary_norad_id` / `secondary_norad_id`
  foreign keys into `objects` instead and joins the names back on read — the
  refs aren't duplicated across 40+ events, and a name correction lands in
  one place.
- `CatalogStatus` has no table. Its funnel counters (`pairs_considered`,
  `events_found`, …) live on `screening_runs`, one row per ingest; its
  epoch-age distribution is computed from `objects.epoch` when asked.
- The list view filters on TCA window, tier, and score, so `tca`,
  `risk_tier`, and `risk_score` are indexed.

**`epoch_age_hours` is computed, never stored.** It means "hours between the
TLE epoch and *now*" — a number that is wrong within a second of being
written. Only `epoch` (an absolute instant) goes in the `objects` table; the
age is derived from `epoch` and the wall clock every time an object is
serialised. Storing it would just be a cache with no invalidation.

`max_epoch_age_hours` on a conjunction *is* stored: it's the age at the
moment of screening, a property of that screening run, not a live value.

The per-event geometry response (both objects re-propagated with SGP4 around
TCA) is genuinely expensive, so it's cached in Redis keyed by `event_id`
with a one-hour TTL. If Redis is down the request still succeeds — it logs a
warning and computes directly.

Schema changes go through Alembic (`cd services/api && alembic upgrade
head`); the `loader` service runs that migration before ingesting.

### Why Compose and not Kubernetes

The manifests in [`k8s/`](k8s/) are a deck artifact — a Deployment and
Service per component, an HPA on the API, and an Ingress — showing the
scaling path if this ran as a hosted service. The demonstration itself runs
on Compose: it is two stateless containers on one laptop, it starts with one
command, and it has no control plane, ingress controller, or image registry
to fail on a conference-room network. Same two containers, three fewer
things that can break.

## The six workstreams

| # | Workstream | Owner doc |
|---|---|---|
| 1 | Orbital core — ingest, propagate, frames | [docs/team/01-orbital-core.md](docs/team/01-orbital-core.md) |
| 2 | Screening & scoring — filters, fine screen, risk score | [docs/team/02-screening-scoring.md](docs/team/02-screening-scoring.md) |
| 3 | Backend & data — FastAPI, Postgres, Redis, Celery | [docs/team/03-backend-data.md](docs/team/03-backend-data.md) |
| 4 | Visualisation — orbit/ground-track, geometry view | [docs/team/04-visualisation.md](docs/team/04-visualisation.md) |
| 5 | Dashboard — event table, filters, alerts | [docs/team/05-dashboard.md](docs/team/05-dashboard.md) |
| 6 | Integration, demo & QA — compose, CI, demo script | [docs/team/06-integration-demo.md](docs/team/06-integration-demo.md) |

See also [docs/architecture.md](docs/architecture.md) for more detail, and
[contracts/README.md](contracts/README.md) for the frozen API/data
contracts every workstream builds against.

## Repository layout

```
prahari/
  contracts/        frozen JSON Schema + fixtures — source of truth
  services/orbital/  pure Python library: ingest, propagate, filter, screen, score
  services/api/      FastAPI app, thin, mock|live data source
  services/worker/   Celery Beat: 6-hourly refresh + screening job
  web/               React + TypeScript + Vite dashboard
  k8s/               scalability artifact only — never on the demo path
  docs/              architecture notes + six team READMEs
```

## Hard constraints

- The live demo runs on **docker-compose**, not Kubernetes.
- Everything runs on a single 8-core laptop — no GPU, no HPC, no paid cloud.
- Feature freeze end of Day 3; workstream 6 owns that call.
