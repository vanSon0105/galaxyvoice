"""Server-side task registry for long-running service tasks.

Tasks run in FastAPI's threadpool (plain ``def`` routes). The registry keeps
the task id, status, a ``threading.Event`` for cancellation and the final
result, so the WebSocket can report progress and clients can cancel over
HTTP. Service functions already accept ``stop_event`` / cancellation events,
so cancel maps directly onto them.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    task_id: str
    kind: str
    status: str = RUNNING
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def __post_init__(self) -> None:
        self.stop_event = threading.Event()


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.Lock()

    def create(self, kind: str) -> TaskRecord:
        record = TaskRecord(task_id=f"{kind}_{uuid.uuid4().hex[:8]}", kind=kind)
        with self._lock:
            self._tasks[record.task_id] = record
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        record = self.get(task_id)
        if record is None or record.status != RUNNING:
            return False
        record.stop_event.set()
        return True

    def finish(
        self,
        task_id: str,
        *,
        status: str,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        record = self.get(task_id)
        if record is None:
            return
        record.status = status
        record.result = result
        record.error = error
        record.finished_at = time.time()

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for record in self._tasks.values() if record.status == RUNNING)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "task_id": record.task_id,
                    "kind": record.kind,
                    "status": record.status,
                    "error": record.error,
                    "created_at": record.created_at,
                    "finished_at": record.finished_at,
                }
                for record in self._tasks.values()
            ]


task_registry = TaskRegistry()
