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
    thread: threading.Thread | None = field(default=None, repr=False, compare=False)

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
        with self._lock:
            record = self._tasks.get(task_id)
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

    def cancel_all(self) -> None:
        with self._lock:
            task_ids = [
                record.task_id for record in self._tasks.values() if record.status == RUNNING
            ]
        for task_id in task_ids:
            self.cancel(task_id)

    def wait_for_running(self, timeout: float) -> list[str]:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            records = list(self._tasks.values())
        for record in records:
            thread = record.thread
            if thread is None or not thread.is_alive():
                continue
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._lock:
            return [
                record.task_id
                for record in self._tasks.values()
                if record.thread is not None and record.thread.is_alive()
            ]

    def finish(
        self,
        task_id: str,
        *,
        status: str,
        result: Any = None,
        error: str | None = None,
    ) -> str | None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            if record.status != RUNNING:
                return record.status
            if record.stop_event.is_set():
                status = CANCELLED
                result = None
                error = None
            record.status = status
            record.result = result
            record.error = error
            record.finished_at = time.time()
            return status

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
    """Run a blocking service function on a tracked thread and publish the
    terminal status over the event bus. TaskCancelledError maps to the
    'cancelled' terminal state."""
    task_id = record.task_id
    event_bus.emit({"type": "task", "task_id": task_id, "status": RUNNING})

    def run() -> None:
        try:
            if record.stop_event.is_set():
                raise TaskCancelledError()
            result = func()
            if record.stop_event.is_set():
                raise TaskCancelledError()
            payload = result_serializer(result) if result_serializer is not None else None
        except TaskCancelledError:
            task_registry.finish(task_id, status=CANCELLED)
            event_bus.emit({"type": "task", "task_id": task_id, "status": CANCELLED})
            return
        except Exception as error:
            status = task_registry.finish(task_id, status=FAILED, error=str(error)) or FAILED
            event = {"type": "task", "task_id": task_id, "status": status}
            if status == FAILED:
                event["error"] = str(error)
            event_bus.emit(event)
            return
        status = task_registry.finish(task_id, status=DONE, result=result) or DONE
        event = {"type": "task", "task_id": task_id, "status": status}
        if status == DONE:
            event["result"] = payload
        event_bus.emit(event)

    thread = threading.Thread(target=run, name=f"task-{task_id}", daemon=True)
    record.thread = thread
    thread.start()
