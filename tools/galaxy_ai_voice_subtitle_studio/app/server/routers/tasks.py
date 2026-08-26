"""Task endpoints: cancel a running task over HTTP."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..event_bus import event_bus
from ..tasks import task_registry

router = APIRouter(prefix="/api")


@router.get("/tasks")
def list_tasks() -> list[dict[str, object]]:
    return task_registry.snapshot()


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, object]:
    record = task_registry.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return next(item for item in task_registry.snapshot() if item["task_id"] == task_id)


@router.post("/tasks/{task_id}/pause")
def pause_task(task_id: str) -> dict[str, bool]:
    if not task_registry.pause(task_id):
        raise HTTPException(status_code=409, detail="Task cannot be paused")
    return {"ok": True}


@router.post("/tasks/{task_id}/resume")
def resume_task(task_id: str) -> dict[str, bool]:
    if not task_registry.resume(task_id):
        raise HTTPException(status_code=409, detail="Task cannot be resumed")
    return {"ok": True}


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict[str, bool]:
    if not task_registry.cancel(task_id):
        raise HTTPException(status_code=404, detail="Task không tồn tại hoặc đã kết thúc")
    event_bus.emit(
        {"type": "event", "kind": "task_cancel_requested", "payload": {"task_id": task_id}}
    )
    return {"ok": True}
