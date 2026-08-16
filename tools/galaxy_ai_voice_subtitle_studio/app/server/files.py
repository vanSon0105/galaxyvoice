"""Serve files produced by tasks (results, draft audio) with Range support.

Only files inside a task's registered result directory or a draft's own
workspace are served; every path is resolved and containment-checked.
FileResponse streams with HTTP Range support (video/audio seeking).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .tasks import task_registry

router = APIRouter(prefix="/api/files")


@router.get("/task/{task_id}/{name:path}")
def task_file(task_id: str, name: str) -> FileResponse:
    record = task_registry.get(task_id)
    result = record.result if record is not None else None
    project_dir = getattr(result, "project_dir", None)
    if project_dir is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy kết quả của task")
    root = Path(project_dir).resolve()
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Đường dẫn không hợp lệ")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File không tồn tại")
    return FileResponse(candidate)
