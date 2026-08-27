"""API-only response envelopes. Not part of contracts/ — these wrap contract
objects for pagination but never redefine their fields.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
