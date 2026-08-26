"""Persistent, cooperative job orchestration for Galaxy workflows."""

from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from ..common.cache import read_json, write_json_atomic
from ..common.errors import TaskCancelledError
from .resources import ResourceScheduler, shared_resource_scheduler

QUEUED = "queued"
RUNNING = "running"
PAUSED = "paused"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"

ACTIVE_STATUSES = frozenset({QUEUED, RUNNING, PAUSED})
TERMINAL_STATUSES = frozenset({DONE, FAILED, CANCELLED, INTERRUPTED})
_SENSITIVE_KEYS = re.compile(
    r"(?:api[_-]?key|token|secret|password|authorization|credential|cookie|bearer)",
    re.I,
)


def default_job_store_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path(tempfile.gettempdir())
    return root / "GalaxyAIStudio" / "state" / "jobs.json"


def _safe_checkpoint(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _safe_checkpoint(item)
            for key, item in value.items()
            if not _SENSITIVE_KEYS.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_checkpoint(item) for item in value]
    return str(value)


@dataclass
class TaskRecord:
    task_id: str
    kind: str
    status: str = RUNNING
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    capability_id: str = ""
    project_id: str = ""
    workflow_id: str = ""
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    resumable: bool = False
    pausable: bool = False
    resource_keys: tuple[str, ...] = ()
    progress: float | None = None
    message: str = ""
    checkpoint: dict[str, Any] = field(default_factory=dict)
    on_cancel: Callable[[], None] | None = field(default=None, repr=False, compare=False)
    thread: threading.Thread | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        if self.status == PAUSED:
            self.pause_event.set()


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> list[dict[str, Any]]:
        with self._lock:
            payload = read_json(self.path)
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            return []
        return [item for item in payload["jobs"] if isinstance(item, dict)]

    def save(self, records: list[TaskRecord]) -> None:
        payload = {
            "schema_version": 1,
            "saved_at": time.time(),
            "jobs": [self._serialize(record) for record in records],
        }
        with self._lock:
            write_json_atomic(self.path, payload)

    @staticmethod
    def _serialize(record: TaskRecord) -> dict[str, Any]:
        return {
            "task_id": record.task_id,
            "kind": record.kind,
            "status": record.status,
            "error": record.error,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "updated_at": record.updated_at,
            "finished_at": record.finished_at,
            "capability_id": record.capability_id,
            "project_id": record.project_id,
            "workflow_id": record.workflow_id,
            "run_id": record.run_id,
            "resumable": record.resumable,
            "pausable": record.pausable,
            "resource_keys": list(record.resource_keys),
            "progress": record.progress,
            "message": record.message,
            "checkpoint": _safe_checkpoint(record.checkpoint),
        }


class TaskContext:
    def __init__(self, registry: "TaskRegistry", record: TaskRecord) -> None:
        self._registry = registry
        self._record = record
        self.task_id = record.task_id
        self.stop_event = record.stop_event

    def check_cancelled(self) -> None:
        if self.stop_event.is_set():
            raise TaskCancelledError()

    def wait_if_paused(self) -> None:
        self.check_cancelled()
        while self._record.pause_event.is_set():
            if self.stop_event.wait(0.1):
                raise TaskCancelledError()

    def report(self, message: str, *, progress: float | None = None) -> None:
        self.wait_if_paused()
        self._registry.report(self.task_id, message, progress=progress)

    def save_checkpoint(self, checkpoint: Mapping[str, Any]) -> None:
        self._registry.save_checkpoint(self.task_id, dict(checkpoint))


ResumeHandler = Callable[[TaskContext], Any]


class TaskRegistry:
    def __init__(
        self,
        *,
        store: JobStore | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
        scheduler: ResourceScheduler | None = None,
    ) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.RLock()
        self._store = store
        self._event_sink = event_sink
        self._scheduler = scheduler or shared_resource_scheduler
        self._resume_handlers: dict[str, tuple[ResumeHandler, Callable[[Any], Any] | None]] = {}
        self._restore()

    def bind_event_sink(self, event_sink: Callable[[dict[str, Any]], None] | None) -> None:
        self._event_sink = event_sink

    def configure_store(self, store: JobStore | None) -> None:
        with self._lock:
            self._store = store
            if store is not None and not self._tasks:
                self._restore()
            self._persist_locked()

    def _restore(self) -> None:
        if self._store is None:
            return
        changed = False
        for payload in self._store.load():
            try:
                record = TaskRecord(
                    task_id=str(payload["task_id"]),
                    kind=str(payload["kind"]),
                    status=str(payload.get("status", INTERRUPTED)),
                    error=payload.get("error"),
                    created_at=float(payload.get("created_at", time.time())),
                    started_at=payload.get("started_at"),
                    updated_at=float(payload.get("updated_at", time.time())),
                    finished_at=payload.get("finished_at"),
                    capability_id=str(payload.get("capability_id", "")),
                    project_id=str(payload.get("project_id", "")),
                    workflow_id=str(payload.get("workflow_id", "")),
                    run_id=str(payload.get("run_id", uuid.uuid4().hex)),
                    resumable=bool(payload.get("resumable", False)),
                    pausable=bool(payload.get("pausable", False)),
                    resource_keys=tuple(payload.get("resource_keys", ())),
                    progress=payload.get("progress"),
                    message=str(payload.get("message", "")),
                    checkpoint=dict(payload.get("checkpoint") or {}),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if record.status in ACTIVE_STATUSES:
                record.status = PAUSED if record.resumable else INTERRUPTED
                record.finished_at = None if record.resumable else time.time()
                record.updated_at = time.time()
                if record.status == PAUSED:
                    record.pause_event.set()
                changed = True
            self._tasks[record.task_id] = record
        if changed:
            self._persist_locked()

    def _persist_locked(self) -> None:
        if self._store is not None:
            self._store.save(list(self._tasks.values()))

    def _emit(self, event: dict[str, Any]) -> None:
        sink = self._event_sink
        if sink is not None:
            try:
                sink(event)
            except Exception:
                pass

    def create(
        self,
        kind: str,
        *,
        capability_id: str = "",
        resumable: bool = False,
        pausable: bool = False,
        project_id: str = "",
        workflow_id: str = "",
        resource_keys: tuple[str, ...] = (),
    ) -> TaskRecord:
        record = TaskRecord(
            task_id=f"{kind}_{uuid.uuid4().hex[:8]}",
            kind=kind,
            capability_id=capability_id,
            resumable=resumable,
            pausable=pausable,
            project_id=project_id,
            workflow_id=workflow_id,
            resource_keys=tuple(resource_keys),
        )
        with self._lock:
            self._tasks[record.task_id] = record
            self._persist_locked()
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def register_resume_handler(
        self,
        kind: str,
        handler: ResumeHandler,
        result_serializer: Callable[[Any], Any] | None = None,
    ) -> None:
        self._resume_handlers[kind] = (handler, result_serializer)

    def submit(
        self,
        record: TaskRecord,
        operation: Callable[[TaskContext], Any],
        result_serializer: Callable[[Any], Any] | None = None,
    ) -> None:
        task_id = record.task_id

        def run() -> None:
            context = TaskContext(self, record)
            try:
                with self._scheduler.acquire(
                    task_id,
                    record.resource_keys,
                    record.stop_event,
                    on_wait=lambda: self._transition(task_id, QUEUED),
                ):
                    self._transition(
                        task_id,
                        PAUSED if record.pause_event.is_set() else RUNNING,
                        started=True,
                    )
                    context.wait_if_paused()
                    result = operation(context)
                    context.check_cancelled()
                    payload = result_serializer(result) if result_serializer else None
            except TaskCancelledError:
                self.finish(task_id, status=CANCELLED)
                self._emit({"type": "task", "task_id": task_id, "status": CANCELLED})
                return
            except Exception as error:
                status = self.finish(task_id, status=FAILED, error=str(error)) or FAILED
                event: dict[str, Any] = {"type": "task", "task_id": task_id, "status": status}
                if status == FAILED:
                    event["error"] = str(error)
                self._emit(event)
                return
            status = self.finish(task_id, status=DONE, result=result) or DONE
            event = {"type": "task", "task_id": task_id, "status": status}
            if status == DONE:
                event["result"] = payload
            self._emit(event)

        thread = threading.Thread(target=run, name=f"task-{task_id}", daemon=True)
        record.thread = thread
        thread.start()

    def _transition(self, task_id: str, status: str, *, started: bool = False) -> None:
        now = time.time()
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return
            record.status = status
            record.updated_at = now
            if started and record.started_at is None:
                record.started_at = now
            self._persist_locked()
        self._emit({"type": "task", "task_id": task_id, "status": status})

    def report(self, task_id: str, message: str, *, progress: float | None = None) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return
            record.message = message
            if progress is not None:
                record.progress = min(1.0, max(0.0, float(progress)))
            record.updated_at = time.time()
            self._persist_locked()
            current_progress = record.progress
        event: dict[str, Any] = {"type": "progress", "task_id": task_id, "message": message}
        if current_progress is not None:
            event["progress"] = current_progress
        self._emit(event)

    def save_checkpoint(self, task_id: str, checkpoint: Mapping[str, Any]) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return
            record.checkpoint = dict(_safe_checkpoint(checkpoint))
            record.updated_at = time.time()
            self._persist_locked()

    def pause(self, task_id: str) -> bool:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None or not record.pausable or record.status not in {RUNNING, QUEUED}:
                return False
            record.pause_event.set()
            record.status = PAUSED
            record.updated_at = time.time()
            self._persist_locked()
        self._emit({"type": "task", "task_id": task_id, "status": PAUSED})
        return True

    def resume(self, task_id: str) -> bool:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None or record.status != PAUSED:
                return False
            if record.thread is not None and record.thread.is_alive():
                record.pause_event.clear()
                record.status = RUNNING
                record.updated_at = time.time()
                self._persist_locked()
                live = True
            else:
                handler_entry = self._resume_handlers.get(record.kind)
                if handler_entry is None:
                    return False
                record.stop_event = threading.Event()
                record.pause_event = threading.Event()
                record.status = RUNNING
                record.finished_at = None
                record.updated_at = time.time()
                self._persist_locked()
                live = False
        if live:
            self._emit({"type": "task", "task_id": task_id, "status": RUNNING})
        else:
            handler, serializer = handler_entry
            self.submit(record, handler, serializer)
        return True

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None or record.status not in ACTIVE_STATUSES:
                return False
            record.stop_event.set()
            record.pause_event.clear()
            on_cancel = record.on_cancel
            live = record.thread is not None and record.thread.is_alive()
            if not live:
                record.status = CANCELLED
                record.finished_at = time.time()
                record.updated_at = record.finished_at
                self._persist_locked()
        self._scheduler.wake()
        if on_cancel is not None:
            try:
                on_cancel()
            except Exception:
                pass
        if not live:
            self._emit({"type": "task", "task_id": task_id, "status": CANCELLED})
        return True

    def cancel_all(self) -> None:
        with self._lock:
            task_ids = [
                record.task_id for record in self._tasks.values() if record.status in ACTIVE_STATUSES
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
            if record.status in TERMINAL_STATUSES:
                return record.status
            if record.stop_event.is_set():
                status, result, error = CANCELLED, None, None
            record.status = status
            record.result = result
            record.error = error
            record.progress = 1.0 if status == DONE else record.progress
            record.finished_at = time.time()
            record.updated_at = record.finished_at
            self._persist_locked()
            return status

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for record in self._tasks.values() if record.status in ACTIVE_STATUSES)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [JobStore._serialize(record) for record in self._tasks.values()]
