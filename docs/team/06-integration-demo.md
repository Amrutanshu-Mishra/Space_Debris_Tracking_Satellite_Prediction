# 06 — Integration, demo & QA

Owns compose wiring, CI, seed data, cross-service tests, the demo script,
and the deck/video. Also owns the **feature-freeze call on Day 3** — after
that, this role is the only one allowed to approve exceptions.

## You own

- `docker-compose.yml`, `.env.example`, `Makefile` (shared with workstream 3
  on the service-definition parts — coordinate before changing ports/env
  vars other roles depend on)
- `.github/workflows/ci.yml`
- `contracts/fixtures/*.sample.json` regeneration (the generator script that
  produced them; see `contracts/README.md` for the freeze rule — the
  *schemas* are workstream-agnostic frozen, but fixture *content* is yours
  to refresh if it needs more/different sample events for the demo)
- The demo script and deck/video (outside this repo, but reference it here)
- `k8s/` — scalability artifact only, low priority, do last if at all

## Do not edit

- `contracts/schemas/` — frozen for everyone, including you. If the demo
  needs a new field, that's a whole-team conversation, not a unilateral
  change on Day 4.
- Any `services/*/prahari_*` or `web/src/{views,components}` domain code —
  you integrate and test other roles' code, you don't write it for them.
  If something's broken, file it back to the owning role via their
  `docs/team/0N-*.md` doc instead of quietly patching around it.

## Contract you consume / produce

You don't own a data contract — you own the thing that proves every other
role's contract actually holds end to end. Concretely: `docker compose up`
must produce a stack where `GET /api/v1/health` returns 200, the dashboard
loads real data, and the WebSocket stream delivers at least one message,
using nothing but this repo and `.env.example`.

## Run just your slice

```bash
cp .env.example .env
make up
curl -sf http://localhost:8000/api/v1/health
open http://localhost:5173
```

CI equivalent: `.github/workflows/ci.yml`'s `compose-smoke` job.

## Day 1 / 2 / 3 targets

- **Day 1**: `docker-compose.yml` boots `api` + `web` in mock mode cleanly
  from a fresh clone (`git clone && cp .env.example .env && make up`); CI's
  `orbital`/`api`/`web` jobs are green (they will be, trivially, since
  everything either passes or is a marked skip — watch for that changing
  to a real failure as other roles unskip tests).
- **Day 2**: `compose-smoke` CI job added and green; cross-service smoke
  test that hits every endpoint in the frozen API surface once against a
  running compose stack, not just the mock-mode unit tests each role
  already has.
- **Day 3**: feature freeze call made and communicated; demo script drafted
  and rehearsed end-to-end at least once against `PRAHARI_DATA_SOURCE=live`
  if it's ready, `mock` as the fallback plan if it isn't. This role decides
  which mode the live demo actually runs in — don't let that decision
  happen accidentally at demo time.

## Definition of done

`.github/workflows/ci.yml` is green on `main`, `compose-smoke` passes
against a fresh `.env` copy, and the demo script has been run once,
narrated, against the actual running stack — not described from memory.

## Known traps

- **Fixing symptoms instead of filing bugs.** If `web/` fails to build
  because of a typo in someone else's component, resist the urge to just
  fix it yourself and move on — a quick message to the owning role (per
  their `docs/team/0N-*.md`) keeps them aware of what's breaking in their
  own code before it happens twice.
- **CI green for the wrong reason.** Early in the hackathon, most tests are
  `@pytest.mark.skip`-marked stubs — CI passing doesn't mean anything works
  yet. Track the *un-skip rate* across `services/orbital/tests/`, not just
  the pass/fail colour, so you notice if Day 3 arrives with tests still
  skipped.
- **docker-compose vs. host-path assumptions.** `PRAHARI_DATA_SOURCE=mock`'s
  fixture loading resolves paths relative to the repo root
  (`services/api/prahari_api/config.py`'s `FIXTURES_DIR`) — if you change
  the compose volume mounts, verify `contracts/` is still mounted into the
  `api` container at the same relative location, or mock mode breaks
  silently inside Docker while still working on the host.
- **Freezing too late.** The Day 3 feature-freeze call only works if it's
  made *on* Day 3, not discovered in retrospect on Day 5. Say it out loud
  in the team channel when you make it.
