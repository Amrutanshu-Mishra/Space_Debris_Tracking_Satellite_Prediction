"""DataSource protocol: the one interface every router is allowed to depend on.

Both mock.py (fixtures, fully working) and live.py (real ingest/screen
pipeline, stub) implement this. Routers never import mock or live directly —
see dependency.py for the PRAHARI_DATA_SOURCE switch.
"""

from __future__ import annotations

from typing import Any, Protocol
from prahari_orbital.models import CatalogObject, CatalogStatus, ConjunctionEvent


class DataSource(Protocol):
    """Everything the API surface needs, independent of mock vs. live backing."""

    async def get_catalog_status(self) -> CatalogStatus:
        """Current ingest/screening health snapshot."""
        ...

    async def list_objects(
        self,
        *,
        query: str | None = None,
        object_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogObject], int]:
        """Search/paginate the catalogue.

        Args:
            query: case-insensitive substring match against object name.
            object_type: exact match against CatalogObject.object_type.
            limit: max rows returned.
            offset: rows to skip, for pagination.

        Returns:
            (page of CatalogObject, total_count before pagination).
        """
        ...

    async def get_object(self, norad_id: int) -> CatalogObject | None:
        """Single object by NORAD id, or None if not in the catalogue."""
        ...

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
        """Search/paginate conjunction events.

        Args:
            tier: exact match against ConjunctionEvent.risk_tier.
            since: ISO 8601 UTC, inclusive lower bound on `tca`.
            until: ISO 8601 UTC, inclusive upper bound on `tca`.
            min_score: inclusive lower bound on `risk_score`.
            limit: max rows returned.
            offset: rows to skip, for pagination.

        Returns:
            (page of ConjunctionEvent, total_count before pagination).
        """
        ...

    async def get_conjunction(self, event_id: str) -> ConjunctionEvent | None:
        """Single conjunction event by id, or None if not found."""
        ...

    async def get_conjunction_geometry(self, event_id: str) -> list[dict[str, Any]]:
        """Position samples around TCA for plotting a close-approach event.
        Returns:
            List of samples, each with at minimum:
            {"t": iso8601 str, "primary_km": [x, y, z], "secondary_km": [x, y, z],
             "separation_km": float}, in GCRS, spanning some window around TCA
            (implementation decides the window; mock.py documents its choice
            inline). Empty list if event_id is not found.
        """
        ...

    async def get_object_track(
        self, norad_id: int, *, hours: float = 24.0
    ) -> list[dict[str, float | str]]:
        """Ground-track / orbit-path points for one object.

        Args:
            norad_id: object to track.
            hours: forward horizon from now, hours.

        Returns:
            List of samples: {"t": iso8601 str, "lat_deg": float, "lon_deg": float,
            "alt_km": float}, WGS84 (see prahari_orbital.frames.itrf_to_lat_lon_alt).
            Empty list if norad_id is not found.
        """
        ...
