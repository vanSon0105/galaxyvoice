"""Task endpoints: cancel a running task over HTTP."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..event_bus import event_bus
from ..tasks import task_registry

router = APIRouter(prefix="/api")


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict[str, bool]:
    if not task_registry.cancel(task_id):
        raise HTTPException(status_code=404, detail="Task không tồn tại hoặc đã kết thúc")
    event_bus.emit(
        {"type": "event", "kind": "task_cancel_requested", "payload": {"task_id": task_id}}
    )
    return {"ok": True}
