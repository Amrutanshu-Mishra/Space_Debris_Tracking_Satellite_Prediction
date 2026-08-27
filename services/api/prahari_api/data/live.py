"""Live DataSource: real ingest/propagate/screen pipeline via prahari_orbital, backed by Postgres.

Stub. Every method's real implementation is "query Postgres for the last
completed screening run's output" — the worker (services/worker) owns
running ingest.py/filters.py/screen.py/scoring.py on a schedule and writing
results to the database; this class only reads them back out.

Do not implement propagation or screening logic here — that belongs in
services/orbital. This module is HTTP-adjacent plumbing only.
"""

from __future__ import annotations

from prahari_orbital.models import CatalogObject, CatalogStatus, ConjunctionEvent

from prahari_api.config import Settings


class LiveDataSource:
    """DataSource implementation reading the worker's screening output from Postgres."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_catalog_status(self) -> CatalogStatus:
        raise NotImplementedError("TODO(backend-data): SELECT latest row from catalog_status table")

    async def list_objects(
        self,
        *,
        query: str | None = None,
        object_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogObject], int]:
        raise NotImplementedError("TODO(backend-data): SELECT ... FROM objects WHERE ... LIMIT/OFFSET, plus COUNT(*)")

    async def get_object(self, norad_id: int) -> CatalogObject | None:
        raise NotImplementedError("TODO(backend-data): SELECT ... FROM objects WHERE norad_id = :norad_id")

    async def list_conjunctions(
        self,
        *,
        tier: str | None = None,
        since: str | None = None,
        until: str | None = None,
        min_score: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ConjunctionEvent], int]:
        raise NotImplementedError("TODO(backend-data): SELECT ... FROM conjunctions WHERE ... LIMIT/OFFSET, plus COUNT(*)")

    async def get_conjunction(self, event_id: str) -> ConjunctionEvent | None:
        raise NotImplementedError("TODO(backend-data): SELECT ... FROM conjunctions WHERE event_id = :event_id")

    async def get_conjunction_geometry(self, event_id: str) -> list[dict[str, float | str]]:
        raise NotImplementedError(
            "TODO(orbital-core + backend-data): re-propagate primary/secondary around "
            "the stored TCA via prahari_orbital.propagate, sample every 10s +/-60s"
        )

    async def get_object_track(
        self, norad_id: int, *, hours: float = 24.0
    ) -> list[dict[str, float | str]]:
        raise NotImplementedError(
            "TODO(orbital-core + backend-data): prahari_orbital.propagate over a time grid, "
            "then frames.gcrs_to_itrf + frames.itrf_to_lat_lon_alt"
        )
