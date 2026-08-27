# CLAUDE.md — guidance for Claude Code sessions in this repo

## What this is

PRAHARI: a space situational awareness prototype for SIH PS-04. Full brief
in `README.md`. This file is operational guidance for an agent working in
this repo, not a restatement of the product brief.

## Non-negotiable

**Never add a `probability_of_collision` field, a `pc` field, or any string
implying `risk_score`/`confidence` are a probability.** This applies to
`contracts/schemas/`, Pydantic models, TypeScript types, API responses,
docstrings, and UI copy. See root README, "Why we don't publish a
probability of collision". If you think you need Pc, stop and ask — don't
implement it by extending `scoring.compute_pc`, which is deliberately
disabled.

## Contracts are frozen

`contracts/schemas/*.schema.json` are the source of truth. Never hand-edit
`services/orbital/prahari_orbital/models.py` or `web/src/api/types/*.d.ts`
directly — edit the schema, then regenerate (`make seed`, see
`contracts/README.md`). If a schema genuinely needs a new field, say so
explicitly and change the schema first, in the same change as any code that
depends on the new field.

## Units and frames

Every function touching a position or velocity must state its coordinate
frame (TEME / GCRS / ITRF) and units (km, km/s, degrees, hours) in its
signature or docstring. `services/orbital/prahari_orbital/frames.py` is the
only place frame conversions happen — never hand-roll a TEME/GCRS/ITRF
conversion inline elsewhere in the codebase.

## Ownership boundaries

See `docs/team/0N-*.md` for the six workstreams' file ownership. If asked
to make a change, check whether it crosses an ownership boundary
(e.g. editing another role's owned files) and flag it rather than silently
doing it — these boundaries exist so six people can work in parallel
without merge conflicts.

## Data source flag

`PRAHARI_DATA_SOURCE=mock|live`, default `mock`. Mock mode is fully
implemented (`services/api/prahari_api/data/mock.py`, backed by
`contracts/fixtures/`) and must keep working — most of the rest of the
pipeline (`services/orbital`, `services/api/prahari_api/data/live.py`,
`services/worker`) is intentionally stubbed with `NotImplementedError`
until the corresponding role implements it. Don't "fix" a stub by making it
silently return fake data instead of raising — that hides real bugs from
whoever implements it next.

## Running things

- `make up` — full docker-compose stack.
- `make test` — orbital + api + web test suites.
- `make lint` — ruff/mypy for Python, eslint/tsc for TypeScript.
- `make seed` — regenerate Pydantic + TypeScript models from `contracts/schemas/`.

Prefer running a single service's tests directly (`cd services/api && pytest -q`)
over the full stack when iterating on one slice.
