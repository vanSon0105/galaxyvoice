from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

from ..common.errors import TaskCancelledError
from .client import OmniVoiceWorkerClient


ResultT = TypeVar("ResultT")


class OmniVoiceTaskCoordinator:
    """Serialize jobs that share one resident worker and cancel only its owner."""

    def __init__(
        self,
        client_factory: Callable[[], OmniVoiceWorkerClient] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._queue_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_task_id: str | None = None
        self._active_client: OmniVoiceWorkerClient | None = None

    def run(
        self,
        task_id: str,
        stop_event: threading.Event,
        operation: Callable[[OmniVoiceWorkerClient], ResultT],
        *,
        client_factory: Callable[[], OmniVoiceWorkerClient] | None = None,
    ) -> ResultT:
        if stop_event.is_set():
            raise TaskCancelledError()
        while not self._queue_lock.acquire(timeout=0.1):
            if stop_event.is_set():
                raise TaskCancelledError()
        try:
            if stop_event.is_set():
                raise TaskCancelledError()
            factory = client_factory or self._client_factory
            if factory is None:
                raise RuntimeError("OmniVoice worker client factory is not configured")
            client = factory()
            with self._state_lock:
                self._active_task_id = task_id
                self._active_client = client
            try:
                return operation(client)
            finally:
                with self._state_lock:
                    if self._active_task_id == task_id:
                        self._active_task_id = None
                        self._active_client = None
        finally:
            self._queue_lock.release()

    def cancel(self, task_id: str) -> None:
        with self._state_lock:
            client = self._active_client if self._active_task_id == task_id else None
        if client is not None:
            client.stop()


shared_omnivoice_task_coordinator = OmniVoiceTaskCoordinator()
