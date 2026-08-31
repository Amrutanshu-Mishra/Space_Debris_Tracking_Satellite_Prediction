"""Startup load + schema validation of the conjunction events file.

In mock mode the API serves a JSON array of screened conjunction events read
from disk once at process start and held in memory. The path comes from
``PRAHARI_EVENTS_PATH`` (see :mod:`prahari_api.config`), defaulting to
``contracts/fixtures/conjunctions.real.json``.

Every event is validated against the frozen
``contracts/schemas/conjunction.schema.json`` before the app will accept it,
reusing :func:`prahari_orbital.scoring.validate_event_dict` so the API and the
orbital pipeline check against exactly the same rules. A missing file,
malformed JSON, or a single schema violation is fatal: the app refuses to
start rather than serve data that does not match the contract.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from prahari_orbital.models import ConjunctionEvent
from prahari_orbital.scoring import validate_event_dict

from prahari_api.config import get_settings


class EventsFileError(RuntimeError):
    """The configured events file is missing, unparseable, or schema-invalid."""


def load_and_validate_events(path: Path) -> list[ConjunctionEvent]:
    """Read, schema-check, and parse the conjunction events file at ``path``.

    Args:
        path: JSON file holding an array of conjunction events.

    Returns:
        The parsed events, in file order.

    Raises:
        EventsFileError: the file does not exist, is not a JSON array, or one
            or more events fail ``contracts/schemas/conjunction.schema.json``.
            The message lists every violation.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EventsFileError(
            f"PRAHARI_EVENTS_PATH points at a file that does not exist: {path}"
        ) from exc

    try:
        parsed: Any = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise EventsFileError(f"{path}: not valid JSON: {exc}") from exc

    if not isinstance(parsed, list):
        raise EventsFileError(
            f"{path}: expected a JSON array of conjunction events, "
            f"got {type(parsed).__name__}"
        )

    problems: list[str] = []
    for index, event in enumerate(parsed):
        if not isinstance(event, dict):
            problems.append(
                f"event[{index}]: expected an object, got {type(event).__name__}"
            )
            continue
        event_dict: dict[str, Any] = event
        event_id = event_dict.get("event_id", "?")
        problems.extend(
            f"event[{index}] ({event_id}): {message}"
            for message in validate_event_dict(event_dict)
        )

    if problems:
        raise EventsFileError(
            f"{path}: {len(problems)} schema violation(s) against "
            f"contracts/schemas/conjunction.schema.json, refusing to start:\n  "
            + "\n  ".join(problems)
        )

    return [ConjunctionEvent.model_validate(event) for event in parsed]


@lru_cache(maxsize=1)
def get_events() -> list[ConjunctionEvent]:
    """Process-wide cached load of the ``PRAHARI_EVENTS_PATH`` events file.

    Reads and schema-validates the file once, then serves the parsed list to
    every caller (the startup hook, the mock data source, ``/health``).

    Raises:
        EventsFileError: propagated from :func:`load_and_validate_events`.
    """
    return load_and_validate_events(get_settings().prahari_events_path)
