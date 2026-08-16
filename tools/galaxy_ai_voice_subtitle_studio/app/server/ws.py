"""Single WebSocket fan-out for state events, task progress and task status.

Message envelope (JSON text frames):
    {"type": "event", "kind": ..., "payload": ...}   # state change -> refetch
    {"type": "progress", "task_id": ..., "message": ...}
    {"type": "task", "task_id": ..., "status": ..., "result": ...}
    {"type": "ping"}                                  # keepalive, 25 s

The connection is one-way (server -> UI); cancellation goes over HTTP
(POST /api/tasks/{id}/cancel).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .event_bus import event_bus

KEEPALIVE_SECONDS = 25.0

router = APIRouter()


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    await websocket.accept()
    # Bind to the loop this connection actually lives on (also covers cases
    # where the app's startup event never ran, e.g. some test harnesses).
    event_bus.bind_loop(asyncio.get_running_loop())
    queue = event_bus.subscribe()
    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                await websocket.send_json(message)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        # CancelledError: uvicorn force-exits during app shutdown; swallowing
        # it keeps the shutdown log clean.
        pass
    finally:
        event_bus.unsubscribe(queue)
