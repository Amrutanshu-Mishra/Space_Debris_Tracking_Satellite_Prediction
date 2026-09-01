"""Optional persistence layer for the PRAHARI API.

The API works with no database at all: unset ``DATABASE_URL`` and the JSON
fixture data source (``prahari_api.data.mock``) serves every endpoint from
memory. Set ``DATABASE_URL`` and the same routes are served from Postgres
through :class:`prahari_api.db.repository.DbDataSource`.

This package holds the three pieces that only matter when a database is
present:

- :mod:`prahari_api.db.tables` -- normalised SQLAlchemy models. They do
  **not** mirror the wire format; see the README "Storage design" section.
- :mod:`prahari_api.db.session` -- async engine / session-maker helpers.
- :mod:`prahari_api.db.repository` -- the ``DataSource`` implementation that
  reads those tables and returns the same Pydantic contract models the JSON
  source returns.
- :mod:`prahari_api.db.cache` -- the best-effort Redis cache for the
  expensive per-event geometry response.
"""

from __future__ import annotations

from prahari_api.db.tables import Base, ConjunctionRow, ObjectRow, ScreeningRunRow

__all__ = ["Base", "ConjunctionRow", "ObjectRow", "ScreeningRunRow"]
