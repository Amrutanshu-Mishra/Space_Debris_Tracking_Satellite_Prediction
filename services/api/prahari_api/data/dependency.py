"""FastAPI dependency that resolves DataSource from PRAHARI_DATA_SOURCE.

The one place mock.py and live.py are both imported. Routers depend on
get_data_source, never on MockDataSource/LiveDataSource directly.
"""

from __future__ import annotations

from prahari_api.config import get_settings
from prahari_api.data.base import DataSource
from prahari_api.data.mock import MockDataSource

_data_source: DataSource | None = None


def get_data_source() -> DataSource:
    global _data_source
    if _data_source is None:
        settings = get_settings()
        if settings.use_database:
            # Imported lazily so mock mode never needs the DB/Redis deps.
            from prahari_api.data.live import LiveDataSource

            _data_source = LiveDataSource(settings)
        else:
            _data_source = MockDataSource()
    return _data_source


def set_data_source(ds: DataSource | None) -> None:
    global _data_source
    _data_source = ds
