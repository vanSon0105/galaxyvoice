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
from typing import Any, Callable

from ..common.errors import TaskCancelledError
from .event_bus import event_bus

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
    on_cancel: Callable[[], None] | None = field(default=None, repr=False, compare=False)

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
        on_cancel = record.on_cancel
        if on_cancel is not None:
            try:
                on_cancel()
            except Exception:
                # The task thread reports its own terminal state; the cancel
                # hook is best-effort (e.g. killing a worker subprocess).
                pass
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


def run_task(
    record: TaskRecord,
    func: Callable[[], Any],
    result_serializer: Callable[[Any], Any] | None = None,
) -> None:
    """Run a blocking service function on a daemon thread and publish the
    terminal status over the event bus. TaskCancelledError maps to the
    'cancelled' terminal state."""
    task_id = record.task_id

    def run() -> None:
        try:
            result = func()
        except TaskCancelledError:
            task_registry.finish(task_id, status=CANCELLED)
            event_bus.emit({"type": "task", "task_id": task_id, "status": CANCELLED})
            return
        except Exception as error:
            task_registry.finish(task_id, status=FAILED, error=str(error))
            event_bus.emit(
                {"type": "task", "task_id": task_id, "status": FAILED, "error": str(error)}
            )
            return
        payload = result_serializer(result) if result_serializer is not None else None
        task_registry.finish(task_id, status=DONE, result=result)
        event_bus.emit(
            {"type": "task", "task_id": task_id, "status": DONE, "result": payload}
        )

    threading.Thread(target=run, name=f"task-{task_id}", daemon=True).start()
