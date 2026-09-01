"""Ingest a screening-result JSON into Postgres.

    python -m prahari_api.load --events contracts/fixtures/conjunctions.real.json

Upserts every referenced object, records one ``screening_runs`` row, and
upserts every conjunction event with that run's id. Idempotent: the run is
keyed by the latest ``screened_at`` in the file, so re-running the same file
updates rows in place instead of duplicating them.

The events file only carries ``{norad_id, name}`` object refs, so full
object rows (TLE lines, epoch, orbit params) come from a companion objects
file -- ``--objects PATH`` or, by default, ``objects.sample.json`` sitting
next to the events file. Funnel counters for the ``screening_runs`` row come
from a companion ``catalog_status.sample.json`` when present, else default
to zero.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from prahari_orbital.models import CatalogObject, ConjunctionEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prahari_api.config import get_settings
from prahari_api.db.session import (
    catalog_object_to_row_kwargs,
    conjunction_event_to_row_kwargs,
    create_db_engine,
    create_session_maker,
    init_db,
)
from prahari_api.db.tables import ConjunctionRow, ObjectRow, ScreeningRunRow
from prahari_api.events import load_and_validate_events


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m prahari_api.load", description=__doc__)
    parser.add_argument("--events", required=True, type=Path, help="screening-result JSON")
    parser.add_argument(
        "--objects",
        type=Path,
        default=None,
        help="object catalogue JSON (default: objects.sample.json beside --events)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy async URL (default: $DATABASE_URL)",
    )
    return parser.parse_args(argv)


def _load_objects(events_path: Path, objects_path: Path | None) -> list[CatalogObject]:
    path = objects_path or events_path.parent / "objects.sample.json"
    if not path.exists():
        raise SystemExit(
            f"objects file not found: {path}\n"
            "pass --objects PATH -- the events file has only norad_id/name refs"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [CatalogObject.model_validate(o) for o in raw]


def _load_run_counters(events_path: Path, events: list[ConjunctionEvent], object_count: int) -> dict:
    """Funnel metadata for the screening_runs row, from catalog_status.sample.json
    if it sits beside the events file, else conservative defaults."""
    counters = {
        "window_hours": get_settings().screening_window_hours,
        "objects_screened": object_count,
        "pairs_considered": 0,
        "pairs_fine_screened": 0,
        "events_found": len(events),
        "duration_s": 0.0,
    }
    status_path = events_path.parent / "catalog_status.sample.json"
    if status_path.exists():
        status = json.loads(status_path.read_text(encoding="utf-8"))
        counters.update(
            window_hours=status.get("screening_window_hours", counters["window_hours"]),
            pairs_considered=status.get("pairs_considered", 0),
            pairs_fine_screened=status.get("pairs_fine_screened", 0),
            events_found=status.get("events_found", len(events)),
            duration_s=status.get("last_screen_duration_s", 0.0),
        )
    return counters


def _run_started_at(events: list[ConjunctionEvent]) -> datetime:
    """Deterministic run identity: the newest screened_at in the file."""
    if not events:
        return datetime.now(UTC)
    latest = max(e.screened_at for e in events)
    return latest if latest.tzinfo else latest.replace(tzinfo=UTC)


async def _upsert_run(session: AsyncSession, started_at: datetime, counters: dict) -> int:
    """One row per screening result. ``started_at`` (the newest screened_at in
    the file) is the identity; matched in Python so a timezone round-trip
    through SQLite doesn't defeat the dedupe."""
    existing = None
    for row in (await session.execute(select(ScreeningRunRow))).scalars().all():
        row_started = row.started_at if row.started_at.tzinfo else row.started_at.replace(tzinfo=UTC)
        if abs((row_started - started_at).total_seconds()) < 1.0:
            existing = row
            break
    if existing is None:
        new_row = ScreeningRunRow(started_at=started_at, **counters)
        session.add(new_row)
        await session.flush()
        return new_row.id
    for key, value in counters.items():
        setattr(existing, key, value)
    await session.flush()
    return existing.id


async def ingest(
    *,
    events_path: Path,
    objects_path: Path | None,
    database_url: str,
) -> dict[str, int]:
    events = load_and_validate_events(events_path)
    objects = _load_objects(events_path, objects_path)

    known_ids = {o.norad_id for o in objects}
    referenced = {e.primary.norad_id for e in events} | {e.secondary.norad_id for e in events}
    missing = sorted(referenced - known_ids)
    if missing:
        raise SystemExit(
            f"{len(missing)} object(s) referenced by events but absent from the objects "
            f"file: {missing[:10]}{' ...' if len(missing) > 10 else ''}"
        )

    engine = create_db_engine(database_url)
    session_maker = create_session_maker(engine)
    try:
        await init_db(engine)
        counters = _load_run_counters(events_path, events, len(objects))
        started_at = _run_started_at(events)
        async with session_maker() as session:
            async with session.begin():
                run_id = await _upsert_run(session, started_at, counters)
                for obj in objects:
                    await session.merge(ObjectRow(**catalog_object_to_row_kwargs(obj)))
                await session.flush()
                for event in events:
                    await session.merge(
                        ConjunctionRow(
                            **conjunction_event_to_row_kwargs(event, screening_run_id=run_id)
                        )
                    )
        return {
            "screening_run_id": run_id,
            "objects": len(objects),
            "conjunctions": len(events),
        }
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    database_url = args.database_url or get_settings().database_url
    if not database_url:
        print("no database configured: pass --database-url or set DATABASE_URL", file=sys.stderr)
        return 2
    result = asyncio.run(
        ingest(
            events_path=args.events,
            objects_path=args.objects,
            database_url=database_url,
        )
    )
    print(
        f"loaded screening_run={result['screening_run_id']}: "
        f"{result['objects']} objects, {result['conjunctions']} conjunctions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
