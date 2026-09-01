"""Live DataSource: the API surface served from Postgres.

The implementation lives in :mod:`prahari_api.db.repository` now that
persistence is its own package; ``LiveDataSource`` stays here as the name
the dependency wiring and tests import. It is selected whenever
``DATABASE_URL`` is set (or ``PRAHARI_DATA_SOURCE=live``); with no database
configured the API uses :class:`prahari_api.data.mock.MockDataSource`
instead and needs no Postgres or Redis container.
"""

from __future__ import annotations

from prahari_api.db.repository import DbDataSource

# Backwards-compatible alias: routers/tests refer to LiveDataSource.
LiveDataSource = DbDataSource

__all__ = ["DbDataSource", "LiveDataSource"]
