"""Web API for subtitle-track removal and burned-in subtitle cleanup."""
from __future__ import annotations

import mimetypes
import tempfile
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...common.processes import managed_media_processes
from ...project_graph.integrations import register_media_result
from ...project_graph.runtime import project_graph_service
from ...subtitle_removal.constants import REMOVAL_MODE_LABELS
from ...subtitle_removal.plan import (
    MAX_REMOVAL_MASKS,
    REGION_PRESETS,
    RemovalMask,
    validate_masks,
)
from ...subtitle_removal.service import (
    BLUR_MODE,
    SUBTITLE_REMOVAL_MODES,
    SubtitleRemovalOptions,
    create_video_preview,
    probe_video_duration,
    probe_video_size,
)
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


class MaskRequest(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    region: RegionRequest
    start_seconds: float = Field(0.0, ge=0)
    end_seconds: float | None = Field(None, gt=0)

    def as_mask(self) -> RemovalMask:
        return RemovalMask(
            self.id.strip(),
            self.name.strip(),
            self.region.as_tuple(),
            self.start_seconds,
            self.end_seconds,
        )


class RemoveRequest(BaseModel):
    galaxy_project_id: str = ""
    video_path: str
    output_dir: str
    project_name: str = ""
    mode: str = BLUR_MODE
    region: RegionRequest = Field(default_factory=RegionRequest)
    blur_strength: int = Field(18, ge=1, le=100)
    masks: list[MaskRequest] = Field(default_factory=list, max_length=MAX_REMOVAL_MASKS)


def _video_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise HTTPException(status_code=422, detail="Video đầu vào không tồn tại.")
    return path


def _progress(record: TaskRecord):
    def report(message: str) -> None:
        task_registry.report(record.task_id, message)

    return report


@router.get("/modes")
def get_modes() -> dict[str, Any]:
    return {
        "modes": [
            {
                "code": code,
                "label": REMOVAL_MODE_LABELS[code],
            }
            for code in SUBTITLE_REMOVAL_MODES
        ],
        "region_presets": [
            {
                "code": preset.code,
                "name": preset.name,
                "region": {
                    "x": preset.region[0],
                    "y": preset.region[1],
                    "width": preset.region[2],
                    "height": preset.region[3],
                },
            }
            for preset in REGION_PRESETS
        ],
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


@router.post("/remove")
def start_removal(body: RemoveRequest, request: Request) -> dict[str, str]:
    video_path = _video_path(body.video_path)
    if body.mode not in SUBTITLE_REMOVAL_MODES:
        raise HTTPException(status_code=422, detail="Chế độ xóa phụ đề không hợp lệ.")
    try:
        region = body.region.as_tuple()
        masks = tuple(item.as_mask() for item in body.masks)
        if masks:
            validate_masks(masks)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not body.output_dir.strip():
        raise HTTPException(status_code=422, detail="Chọn thư mục xuất trước khi xử lý.")
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
        masks=masks,
    )
    record = task_registry.create(
        "subtitle-removal",
        capability_id="media.ffmpeg",
    )
    record.on_cancel = lambda: managed_media_processes.terminate_task(record.task_id)
    configured = getattr(request.app.state, "settings_path", None)
    graph_service = project_graph_service(Path(configured) if configured is not None else None)

    def run_removal():
        from ...subtitle_removal.service import remove_subtitles_from_video

        return remove_subtitles_from_video(
            options,
            progress=_progress(record),
            stop_event=record.stop_event,
            task_id=record.task_id,
        )

    def serialize(result: Any) -> dict[str, Any]:
        register_media_result(
            graph_service,
            project_id=body.galaxy_project_id,
            workspace="subtitle_removal",
            owner_id=record.task_id,
            label=body.project_name or video_path.stem,
            sources=(("source_video", str(video_path)),),
            outputs=(
                ("clean_video", str(result.video_path)),
                ("manifest", str(result.manifest_path)),
            ),
            metadata={"mode": result.mode, "mask_count": len(options.resolved_masks)},
        )
        return {
            "project_dir": str(result.project_dir),
            "video_path": str(result.video_path),
            "video_url": f"/api/files/task/{record.task_id}/{result.video_path.name}",
            "manifest_path": str(result.manifest_path),
            "mode": result.mode,
            "warnings": list(result.warnings),
            "source_video_path": str(video_path),
            "masks": [
                {
                    "id": mask.mask_id,
                    "name": mask.name,
                    "region": {
                        "x": mask.region[0],
                        "y": mask.region[1],
                        "width": mask.region[2],
                        "height": mask.region[3],
                    },
                    "start_seconds": mask.start_seconds,
                    "end_seconds": mask.end_seconds,
                }
                for mask in options.resolved_masks
            ],
        }

    run_task(record, run_removal, serialize)
    return {"task_id": record.task_id}


def reset_removal_sources() -> None:
    with _sources_lock:
        _sources.clear()
        _source_order.clear()
