"""Compatibility facade over Galaxy's shared runtime job orchestrator."""

from __future__ import annotations

from typing import Any, Callable

from ..runtime.jobs import (
    CANCELLED,
    DONE,
    FAILED,
    INTERRUPTED,
    PAUSED,
    QUEUED,
    RUNNING,
    TaskRecord,
    TaskRegistry,
)
from ..runtime.resources import shared_resource_scheduler
from .event_bus import event_bus


task_registry = TaskRegistry(
    event_sink=event_bus.emit,
    scheduler=shared_resource_scheduler,
)


def run_task(
    record: TaskRecord,
    func: Callable[[], Any],
    result_serializer: Callable[[Any], Any] | None = None,
) -> None:
    """Run a legacy blocking service through the shared job runner."""

    task_registry.submit(record, lambda _context: func(), result_serializer)


__all__ = [
    "CANCELLED",
    "DONE",
    "FAILED",
    "INTERRUPTED",
    "PAUSED",
    "QUEUED",
    "RUNNING",
    "TaskRecord",
    "TaskRegistry",
    "run_task",
    "task_registry",
]
