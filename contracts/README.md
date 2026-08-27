# contracts/

This directory is the **source of truth** for every shape that crosses a
service boundary in PRAHARI. Nothing downstream is allowed to invent its own
version of these shapes.

## The freeze rule

The three schemas in `schemas/` are frozen for the duration of the hackathon:

- `object.schema.json`
- `conjunction.schema.json`
- `catalog_status.schema.json`

If a field is missing and you need it, do not add it silently. Post in the
team channel, get agreement, bump the schema, regenerate models on both
sides in the same PR. A silent drift between the Python models and the
TypeScript types is the single most likely way this project breaks under
demo pressure.

`fixtures/` holds hand-curated sample data that **validates against** the
schemas above:

- `objects.sample.json` — 200 catalogue objects, real NORAD IDs for
  well-known satellites (ISS, HST, Landsat, Sentinel, NOAA, Starlink) mixed
  with synthetic payloads/rocket-bodies/debris to reach 200.
- `conjunctions.sample.json` — 40 conjunction events, ~4 RED / ~12 AMBER /
  ~24 GREEN, miss distances 0.1–20 km, relative velocities 0.3–14.5 km/s,
  epoch ages 2–200 h.
- `catalog_status.sample.json` — one ingest-health snapshot.

These fixtures back `PRAHARI_DATA_SOURCE=mock` (the default) end to end, so
frontend, API, and visualisation work can proceed without a working
propagator.

## Regenerating models from schemas

**Python (Pydantic)** — used by `services/orbital` and `services/api`:

```bash
cd services/orbital
python -m datamodel_code_generator \
  --input ../../contracts/schemas \
  --input-file-type jsonschema \
  --output prahari_orbital/models.py \
  --target-python-version 3.11 \
  --use-schema-description \
  --field-constraints
```

`prahari_orbital/models.py` is checked in as generated output. Do not hand-edit it —
edit the schema and regenerate.

**TypeScript** — used by `web/src/api`:

```bash
cd web
npx json-schema-to-typescript ../contracts/schemas/object.schema.json \
  -o src/api/types/object.d.ts
npx json-schema-to-typescript ../contracts/schemas/conjunction.schema.json \
  -o src/api/types/conjunction.d.ts
npx json-schema-to-typescript ../contracts/schemas/catalog_status.schema.json \
  -o src/api/types/catalog_status.d.ts
```

Both codegen steps are wired into `make seed` (see root `Makefile`) so a
fresh checkout regenerates everything in one command.

## Non-negotiable field

`conjunction.schema.json` deliberately has no `probability_of_collision`
field and never will. See the root README section "Why we don't publish a
probability of collision". `risk_score` and `confidence` are the only
risk-facing numbers this system emits.
