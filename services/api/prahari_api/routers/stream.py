"""WS /api/v1/stream — pushes new/updated ConjunctionEvent messages.

Message shape: {"type": "snapshot" | "event", "data": ConjunctionEvent | list[ConjunctionEvent]}.
On connect: one "snapshot" message with every currently-known event.
Thereafter: one "event" message per new/updated event.

In mock mode this is fully working — it replays fixture events on a timer
so the frontend has a real stream to build against on Day 1. In live mode
it subscribes to the Redis pub/sub channel the worker publishes to after
each screening run (see services/worker).
"""

from __future__ import annotations

import asyncio
import json
import random

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from prahari_api.config import get_settings
from prahari_api.data import get_data_source

router = APIRouter(tags=["stream"])

MOCK_REPLAY_INTERVAL_S = 15.0


@router.websocket("/stream")
async def stream(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    data = get_data_source()

    events, _ = await data.list_conjunctions(limit=500, offset=0)
    await websocket.send_json(
        {"type": "snapshot", "data": [e.model_dump(mode="json") for e in events]}
    )

    if settings.prahari_data_source == "mock":
        try:
            while True:
                await asyncio.sleep(MOCK_REPLAY_INTERVAL_S)
                if not events:
                    continue
                replayed = random.choice(events)
                await websocket.send_json(
                    {"type": "event", "data": replayed.model_dump(mode="json")}
                )
        except WebSocketDisconnect:
            return
    else:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
        pubsub = redis_client.pubsub()
        try:
            await pubsub.subscribe(settings.conjunction_stream_channel)
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    raw_data = message["data"]
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode("utf-8")
                    event_data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                    await websocket.send_json({"type": "event", "data": event_data})
                await asyncio.sleep(0.01)
        except WebSocketDisconnect:
            pass
        finally:
            try:
                await pubsub.unsubscribe(settings.conjunction_stream_channel)
                await pubsub.close()
                await redis_client.aclose()
            except (OSError, ConnectionError):
                pass
