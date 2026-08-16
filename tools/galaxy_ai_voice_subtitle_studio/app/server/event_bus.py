"""Thread-safe event fan-out for the web shell.

Service workers (plain threads) emit dict messages; the WebSocket handler
delivers them to the connected UI. ``emit`` is safe to call from any thread:
delivery is marshalled onto the event loop via ``call_soon_threadsafe``.
Slow consumers drop the oldest message first so a stuck UI never blocks a
worker thread or grows memory without bound.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

MAX_QUEUE_SIZE = 256


class EventBus:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register the loop running the WebSocket handlers (set at app startup)."""
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def emit(self, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            try:
                loop.call_soon_threadsafe(self._deliver, queue, message)
            except RuntimeError:
                # Loop already shut down; nothing left to deliver to.
                pass

    def _deliver(self, queue: asyncio.Queue[dict[str, Any]], message: dict[str, Any]) -> None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # Drop the oldest message to make room; task-done events must
            # always be able to reach the UI.
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass


event_bus = EventBus()
