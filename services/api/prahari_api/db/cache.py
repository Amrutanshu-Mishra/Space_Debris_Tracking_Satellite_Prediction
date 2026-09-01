"""Best-effort Redis cache for the per-event geometry response.

``get_conjunction_geometry`` re-propagates both objects with SGP4 across a
window around TCA. That is genuinely expensive and the result is stable for
a given screening run, so it is cached in Redis keyed by ``event_id`` with a
one-hour TTL.

The cache is never allowed to break a request. If Redis is unreachable (or
the ``redis`` package is not installed), every method logs one warning and
degrades to "no cache": the caller computes directly. A poisoned/oversized
value is treated as a miss.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("prahari_api.db.cache")

_KEY_PREFIX = "prahari:geometry:"


class GeometryCache:
    def __init__(self, redis_url: str | None, *, ttl_seconds: int = 3600) -> None:
        self._redis_url = redis_url
        self._ttl_seconds = ttl_seconds
        self._client: Any | None = None
        self._disabled = not redis_url
        self._warned = False

    def _warn_once(self, message: str) -> None:
        if not self._warned:
            logger.warning("geometry cache unavailable, computing directly: %s", message)
            self._warned = True

    async def _get_client(self) -> Any | None:
        if self._disabled:
            return None
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as aioredis
        except ImportError as exc:  # pragma: no cover - redis is a declared dep
            self._disabled = True
            self._warn_once(f"redis package not importable ({exc})")
            return None
        try:
            self._client = aioredis.from_url(  # type: ignore[no-untyped-call]
                self._redis_url, socket_connect_timeout=1, socket_timeout=1
            )
        except (OSError, ValueError) as exc:
            self._disabled = True
            self._warn_once(str(exc))
            return None
        return self._client

    async def get(self, event_id: str) -> list[dict[str, Any]] | None:
        client = await self._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(_KEY_PREFIX + event_id)
        except Exception as exc:  # noqa: BLE001 - any redis failure is non-fatal
            self._warn_once(str(exc))
            return None
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return value if isinstance(value, list) else None

    async def set(self, event_id: str, value: list[dict[str, Any]]) -> None:
        client = await self._get_client()
        if client is None:
            return
        try:
            await client.set(
                _KEY_PREFIX + event_id, json.dumps(value), ex=self._ttl_seconds
            )
        except Exception as exc:  # noqa: BLE001 - any redis failure is non-fatal
            self._warn_once(str(exc))

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
