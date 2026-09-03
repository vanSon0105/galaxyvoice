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
from typing import Any, Callable, Mapping, TypeVar

from ..common.cache import read_json, write_json_atomic
from ..common.diagnostics import get_logger, redact_sensitive_text
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
    r"(?:api[_-]?key|token|secret|password|authorization|credential|cookie|bearer)", re.I
)
LOGGER = get_logger("runtime.jobs")
MAX_TASK_LOG_LINES = 100
MAX_TASK_RECORDS = 200
PROGRESS_PERSIST_INTERVAL_SECONDS = 1.0
_RECOVERY_DEFAULTS: dict[str, tuple[str, str]] = {
    "native-parity-validation": (
        "/settings/parity",
        "Mở Thiết lập đối chiếu native để xem bằng chứng và chạy lại phần chưa hoàn tất.",
    ),
    "studio-generate": ("/voice", "Mở Studio và chạy lại bản đọc từ nội dung đã lưu."),
    "voice-batch": ("/voice/batch", "Mở Batch để tiếp tục hoặc chạy lại các mục chưa xong."),
    "omnivoice-batch": ("/voice/batch", "Mở Batch để tiếp tục từ checkpoint gần nhất."),
    "transcript-asr": ("/voice/transcripts", "Mở Transcripts và nhập lại tệp media."),
    "workspace-render": ("/voice/longform", "Mở project và tiếp tục render từ checkpoint."),
    "dubbing-translate": ("/voice/dubbing", "Mở Dubbing và dịch lại; cache đã hoàn thành sẽ được dùng lại."),
    "audio-separation": ("/separation", "Mở Tách âm thanh và chạy lại với thiết lập đã lưu."),
    "subtitle-removal": ("/removal", "Mở Xóa phụ đề và chạy lại video."),
    "video-editor": ("/editor", "Mở Dựng video và xuất lại project."),
    "transcribe": ("/dubbing", "Mở Phụ đề video và tạo lại phụ đề."),
    "generate": ("/dubbing", "Mở Phụ đề video và tạo lại giọng đọc."),
    "extract-audio": ("/dubbing", "Mở Phụ đề video và trích âm thanh lại."),
    "omnivoice-generate": ("/voice", "Mở Studio và tạo lại bản đọc."),
    "omnivoice-install": ("/settings", "Mở Thiết lập máy và cài lại OmniVoice runtime."),
    "model-install": ("/settings", "Mở Cài đặt và cài lại model."),
    "audio-model-download": ("/separation", "Mở Tách âm thanh và tải lại model."),
    "audio-separator-install": ("/separation", "Mở Tách âm thanh và cài lại runtime."),
    "audio-post-export": ("/voice", "Mở workspace và xuất lại bản hậu kỳ audio."),
}


def default_job_store_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path(tempfile.gettempdir())
    return root / "GalaxyAIStudio" / "state" / "jobs.json"


def _safe_checkpoint(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if value is None or isinstance(value, (int, float, bool)):
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
    result_payload: Any = None
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
    logs: list[str] = field(default_factory=list)
    recovery_route: str = ""
    recovery_hint: str = ""
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
            "error": redact_sensitive_text(record.error) if record.error else None,
            "result": _safe_checkpoint(record.result_payload),
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
            "message": redact_sensitive_text(record.message),
            "checkpoint": _safe_checkpoint(record.checkpoint),
            "logs": [redact_sensitive_text(item) for item in record.logs[-MAX_TASK_LOG_LINES:]],
            "recovery_route": record.recovery_route,
            "recovery_hint": record.recovery_hint,
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
_T = TypeVar("_T")


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
        self._last_progress_persist_at: dict[str, float] = {}
        self._progress_flush_timers: dict[str, threading.Timer] = {}
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
                    error=(
                        redact_sensitive_text(payload.get("error"))
                        if payload.get("error")
                        else None
                    ),
                    result_payload=_safe_checkpoint(payload.get("result")),
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
                    message=redact_sensitive_text(str(payload.get("message", ""))),
                    checkpoint=dict(payload.get("checkpoint") or {}),
                    logs=[redact_sensitive_text(item) for item in payload.get("logs", [])][
                        -MAX_TASK_LOG_LINES:
                    ],
                    recovery_route=str(payload.get("recovery_route", "")),
                    recovery_hint=str(payload.get("recovery_hint", "")),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if record.status in ACTIVE_STATUSES:
                # Python threads and subprocess handles cannot survive a process restart.
                # Workflow repositories own checkpoint resume; the task points users back
                # there instead of pretending its old thread can continue.
                record.status = INTERRUPTED
                record.finished_at = time.time()
                record.updated_at = time.time()
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
        run_id: str | None = None,
        resource_keys: tuple[str, ...] = (),
        recovery_route: str = "",
        recovery_hint: str = "",
    ) -> TaskRecord:
        default_route, default_hint = _RECOVERY_DEFAULTS.get(kind, ("", ""))
        record = TaskRecord(
            task_id=f"{kind}_{uuid.uuid4().hex[:8]}",
            kind=kind,
            capability_id=capability_id,
            resumable=resumable,
            pausable=pausable,
            project_id=project_id,
            workflow_id=workflow_id,
            run_id=run_id or uuid.uuid4().hex,
            resource_keys=tuple(resource_keys),
            recovery_route=recovery_route or default_route,
            recovery_hint=recovery_hint or default_hint,
        )
        with self._lock:
            self._tasks[record.task_id] = record
            try:
                self._prune_locked()
                self._persist_locked()
            except Exception:
                self._tasks.pop(record.task_id, None)
                raise
        return record

    def _prune_locked(self) -> None:
        overflow = len(self._tasks) - MAX_TASK_RECORDS
        if overflow <= 0:
            return
        terminal = sorted(
            (record for record in self._tasks.values() if record.status in TERMINAL_STATUSES),
            key=lambda record: record.updated_at,
        )
        for record in terminal[:overflow]:
            self._tasks.pop(record.task_id, None)
            self._last_progress_persist_at.pop(record.task_id, None)
            timer = self._progress_flush_timers.pop(record.task_id, None)
            if timer is not None:
                timer.cancel()

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def run_with_task_guard(
        self,
        task_id: str,
        operation: Callable[[TaskRecord], _T],
    ) -> _T:
        """Keep a task stable while a guarded cross-repository operation commits."""
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                raise KeyError(task_id)
            return operation(record)

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
        terminal_callback: Callable[[str, Any, BaseException | None], None] | None = None,
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
                    safe_payload = _safe_checkpoint(payload)
                    status = self.finish(
                        task_id,
                        status=DONE,
                        result=result,
                        result_payload=safe_payload,
                        before_finish=terminal_callback,
                    ) or DONE
            except TaskCancelledError:
                try:
                    self.finish(
                        task_id,
                        status=CANCELLED,
                        before_finish=terminal_callback,
                    )
                except Exception:
                    self.finish(task_id, status=CANCELLED)
                self._emit({"type": "task", "task_id": task_id, "status": CANCELLED})
                return
            except Exception as error:
                LOGGER.error(
                    "Task %s (%s) failed: %s",
                    task_id,
                    record.kind,
                    redact_sensitive_text(error),
                )
                try:
                    status = self.finish(
                        task_id,
                        status=FAILED,
                        error=str(error),
                        before_finish=terminal_callback,
                    ) or FAILED
                except Exception:
                    status = self.finish(task_id, status=FAILED, error=str(error)) or FAILED
                event: dict[str, Any] = {"type": "task", "task_id": task_id, "status": status}
                if status == FAILED:
                    finished = self.get(task_id)
                    event["error"] = (
                        finished.error if finished is not None else redact_sensitive_text(error)
                    )
                self._emit(event)
                return
            event = {"type": "task", "task_id": task_id, "status": status}
            if status == DONE:
                event["result"] = safe_payload
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
        safe_message = redact_sensitive_text(message)
        timer_to_start: threading.Timer | None = None
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return
            record.message = safe_message
            if not record.logs or record.logs[-1] != safe_message:
                record.logs.append(safe_message)
                del record.logs[:-MAX_TASK_LOG_LINES]
            if progress is not None:
                record.progress = min(1.0, max(0.0, float(progress)))
            record.updated_at = time.time()
            monotonic_now = time.monotonic()
            last_persisted = self._last_progress_persist_at.get(task_id, 0.0)
            terminal_progress = progress is not None and record.progress == 1.0
            if terminal_progress or monotonic_now - last_persisted >= PROGRESS_PERSIST_INTERVAL_SECONDS:
                timer = self._progress_flush_timers.pop(task_id, None)
                if timer is not None:
                    timer.cancel()
                self._persist_locked()
                self._last_progress_persist_at[task_id] = monotonic_now
            elif task_id not in self._progress_flush_timers:
                delay = max(
                    0.01,
                    PROGRESS_PERSIST_INTERVAL_SECONDS - (monotonic_now - last_persisted),
                )
                timer_to_start = threading.Timer(delay, self._flush_progress, args=(task_id,))
                timer_to_start.daemon = True
                self._progress_flush_timers[task_id] = timer_to_start
            current_progress = record.progress
        if timer_to_start is not None:
            timer_to_start.start()
        event: dict[str, Any] = {
            "type": "progress",
            "task_id": task_id,
            "message": safe_message,
        }
        if current_progress is not None:
            event["progress"] = current_progress
        self._emit(event)

    def _flush_progress(self, task_id: str) -> None:
        with self._lock:
            self._progress_flush_timers.pop(task_id, None)
            if task_id not in self._tasks:
                return
            self._persist_locked()
            self._last_progress_persist_at[task_id] = time.monotonic()

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
                timer = self._progress_flush_timers.pop(task_id, None)
                if timer is not None:
                    timer.cancel()
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
        result_payload: Any = None,
        error: str | None = None,
        before_finish: Callable[[str, Any, BaseException | None], None] | None = None,
    ) -> str | None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            if record.status in TERMINAL_STATUSES:
                return record.status
            if record.stop_event.is_set():
                status, result, error = CANCELLED, None, None
            if before_finish is not None:
                callback_error = RuntimeError(error) if error else None
                before_finish(status, result, callback_error)
            record.status = status
            record.result = result
            record.result_payload = _safe_checkpoint(result_payload)
            record.error = redact_sensitive_text(error) if error else None
            record.progress = 1.0 if status == DONE else record.progress
            record.finished_at = time.time()
            record.updated_at = record.finished_at
            self._persist_locked()
            self._last_progress_persist_at.pop(task_id, None)
            timer = self._progress_flush_timers.pop(task_id, None)
            if timer is not None:
                timer.cancel()
            return status

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for record in self._tasks.values() if record.status in ACTIVE_STATUSES)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            snapshots: list[dict[str, Any]] = []
            for record in self._tasks.values():
                item = JobStore._serialize(record)
                item.update(
                    {
                        "result": record.result_payload if record.status == DONE else None,
                        "can_pause": record.pausable and record.status in {RUNNING, QUEUED},
                        "can_resume": record.status == PAUSED
                        and (
                            (record.thread is not None and record.thread.is_alive())
                            or record.kind in self._resume_handlers
                        ),
                        "can_cancel": record.status in ACTIVE_STATUSES,
                    }
                )
                snapshots.append(item)
            return snapshots
