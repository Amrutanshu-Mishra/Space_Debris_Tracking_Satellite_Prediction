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
    await websocket.send_json({"type": "snapshot", "data": [e.model_dump(mode="json") for e in events]})

    if settings.prahari_data_source != "mock":
        raise NotImplementedError(
            "TODO(backend-data): subscribe to the worker's Redis pub/sub channel "
            "and forward each published ConjunctionEvent as {'type': 'event', 'data': ...}"
        )

    try:
        while True:
            await asyncio.sleep(MOCK_REPLAY_INTERVAL_S)
            if not events:
                continue
            replayed = random.choice(events)
            await websocket.send_json({"type": "event", "data": replayed.model_dump(mode="json")})
    except WebSocketDisconnect:
        return
