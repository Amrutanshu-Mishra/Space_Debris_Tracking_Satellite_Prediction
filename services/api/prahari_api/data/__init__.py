"""Data-source abstraction. Every router depends on DataSource, never directly
on mock.py or live.py, so PRAHARI_DATA_SOURCE=mock|live is a one-line swap.
"""

from prahari_api.data.base import DataSource
from prahari_api.data.dependency import get_data_source, set_data_source

__all__ = ["DataSource", "get_data_source", "set_data_source"]
