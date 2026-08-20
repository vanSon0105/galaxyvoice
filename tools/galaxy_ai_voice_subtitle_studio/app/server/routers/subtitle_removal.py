"""Web API for subtitle-track removal and burned-in subtitle cleanup."""
from __future__ import annotations

import mimetypes
import subprocess
import tempfile
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...common.paths import studio_root
from ...common.processes import managed_media_processes
from ...subtitle_removal.constants import REMOVAL_MODE_LABELS
from ...subtitle_removal.propainter import resolve_propainter_runtime
from ...subtitle_removal.service import (
    AI_INPAINT_MODES,
    BLUR_MODE,
    SUBTITLE_REMOVAL_MODES,
    SubtitleRemovalOptions,
    create_video_preview,
    probe_video_duration,
    probe_video_size,
)
from ..event_bus import event_bus
from ..tasks import TaskRecord, run_task, task_registry

router = APIRouter(prefix="/api/removal", tags=["subtitle-removal"])

_sources: dict[str, Path] = {}
_source_order: deque[str] = deque()
_sources_lock = threading.Lock()
_MAX_REGISTERED_SOURCES = 32


class RegionRequest(BaseModel):
    x: int = Field(5, ge=0, le=99)
    y: int = Field(75, ge=0, le=99)
    width: int = Field(90, ge=1, le=100)
    height: int = Field(20, ge=1, le=100)

    def as_tuple(self) -> tuple[int, int, int, int]:
        if self.x + self.width > 100 or self.y + self.height > 100:
            raise ValueError("Vùng phụ đề phải nằm hoàn toàn trong khung hình.")
        return self.x, self.y, self.width, self.height


class SourceRequest(BaseModel):
    video_path: str


class PreviewRequest(BaseModel):
    video_path: str
    timestamp_seconds: float = Field(0.0, ge=0)
    region: RegionRequest = Field(default_factory=RegionRequest)


class RemoveRequest(BaseModel):
    video_path: str
    output_dir: str
    project_name: str = ""
    mode: str = BLUR_MODE
    region: RegionRequest = Field(default_factory=RegionRequest)
    blur_strength: int = Field(18, ge=1, le=100)
    processing_device: str = "auto"
    license_accepted: bool = False


def _video_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise HTTPException(status_code=422, detail="Video đầu vào không tồn tại.")
    return path


def _progress(record: TaskRecord):
    def report(message: str) -> None:
        event_bus.emit({"type": "progress", "task_id": record.task_id, "message": message})

    return report


@router.get("/modes")
def get_modes() -> dict[str, Any]:
    try:
        runtime = resolve_propainter_runtime()
        propainter_ready = True
        runtime_path = str(runtime.python_executable)
    except RuntimeError:
        propainter_ready = False
        runtime_path = ""
    return {
        "modes": [
            {
                "code": code,
                "label": REMOVAL_MODE_LABELS[code],
                "uses_ai": code in AI_INPAINT_MODES,
            }
            for code in SUBTITLE_REMOVAL_MODES
        ],
        "propainter_ready": propainter_ready,
        "runtime_path": runtime_path,
        "installer_available": (studio_root() / "install_propainter.ps1").is_file(),
    }


@router.post("/source")
def register_source(body: SourceRequest) -> dict[str, Any]:
    path = _video_path(body.video_path)
    try:
        width, height = probe_video_size(path)
        duration = probe_video_duration(path)
    except RuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    source_id = uuid.uuid4().hex
    with _sources_lock:
        _sources[source_id] = path
        _source_order.append(source_id)
        while len(_source_order) > _MAX_REGISTERED_SOURCES:
            _sources.pop(_source_order.popleft(), None)
    return {
        "source_id": source_id,
        "url": f"/api/removal/source/{source_id}",
        "width": width,
        "height": height,
        "duration": duration,
        "name": path.name,
    }


@router.get("/source/{source_id}")
def stream_source(source_id: str) -> FileResponse:
    with _sources_lock:
        path = _sources.get(source_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Nguồn video không còn khả dụng.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@router.post("/preview")
def preview_frame(body: PreviewRequest, background_tasks: BackgroundTasks) -> FileResponse:
    path = _video_path(body.video_path)
    try:
        body.region.as_tuple()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    preview_root = Path(tempfile.gettempdir()) / "GalaxyAIStudio" / "removal-previews"
    preview_path = preview_root / f"{uuid.uuid4().hex}.jpg"
    try:
        create_video_preview(path, preview_path, timestamp_seconds=body.timestamp_seconds)
    except RuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    background_tasks.add_task(preview_path.unlink, missing_ok=True)
    return FileResponse(preview_path, media_type="image/jpeg", background=background_tasks)


@router.post("/install")
def install_propainter(body: dict[str, Any]) -> dict[str, bool]:
    installer = studio_root() / "install_propainter.ps1"
    if not installer.is_file():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy bộ cài: {installer}")
    device = str(body.get("device") or "auto")
    try:
        subprocess.Popen(
            [
                "powershell",
                "-NoExit",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(installer),
                "-Device",
                device,
            ],
            cwd=installer.parent,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Không mở được bộ cài: {error}") from error
    return {"ok": True}


@router.post("/remove")
def start_removal(body: RemoveRequest) -> dict[str, str]:
    video_path = _video_path(body.video_path)
    if body.mode not in SUBTITLE_REMOVAL_MODES:
        raise HTTPException(status_code=422, detail="Chế độ xóa phụ đề không hợp lệ.")
    try:
        region = body.region.as_tuple()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not body.output_dir.strip():
        raise HTTPException(status_code=422, detail="Chọn thư mục xuất trước khi xử lý.")
    if body.mode in AI_INPAINT_MODES and not body.license_accepted:
        raise HTTPException(
            status_code=422,
            detail="Cần xác nhận license phi thương mại của ProPainter trước khi chạy AI.",
        )

    options = SubtitleRemovalOptions(
        video_path=video_path,
        output_dir=Path(body.output_dir).expanduser(),
        project_name=body.project_name,
        mode=body.mode,
        region_x=region[0],
        region_y=region[1],
        region_width=region[2],
        region_height=region[3],
        blur_strength=body.blur_strength,
        processing_device=body.processing_device,
    )
    record = task_registry.create("subtitle-removal")
    record.on_cancel = lambda: managed_media_processes.terminate_task(record.task_id)

    def run_removal():
        from ...subtitle_removal.service import remove_subtitles_from_video

        return remove_subtitles_from_video(
            options,
            progress=_progress(record),
            stop_event=record.stop_event,
            task_id=record.task_id,
        )

    def serialize(result: Any) -> dict[str, Any]:
        return {
            "project_dir": str(result.project_dir),
            "video_path": str(result.video_path),
            "video_url": f"/api/files/task/{record.task_id}/{result.video_path.name}",
            "manifest_path": str(result.manifest_path),
            "mode": result.mode,
            "warnings": list(result.warnings),
        }

    run_task(record, run_removal, serialize)
    return {"task_id": record.task_id}


def reset_removal_sources() -> None:
    with _sources_lock:
        _sources.clear()
        _source_order.clear()
