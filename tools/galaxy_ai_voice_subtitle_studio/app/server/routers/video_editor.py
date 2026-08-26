"""Web API for the lightweight video editor workspace."""
from __future__ import annotations

import mimetypes
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...common.processes import managed_media_processes
from ...video_editor.service import (
    EDITOR_AUDIO_MODES,
    EDITOR_ENCODERS,
    EDITOR_FPS_OPTIONS,
    EDITOR_RESOLUTIONS,
    EditorExportOptions,
    EditorVideoSegment,
    load_editor_subtitles,
    probe_audio_duration,
    probe_editor_media,
)
from ...voice.srt import SubtitleCue
from ..event_bus import event_bus
from ...runtime.resources import resource_keys_for_device
from ..tasks import TaskRecord, run_task, task_registry

router = APIRouter(prefix="/api/editor", tags=["video-editor"])

_sources: dict[str, Path] = {}
_source_order: deque[str] = deque()
_sources_lock = threading.Lock()
_MAX_REGISTERED_SOURCES = 48


class LoadRequest(BaseModel):
    path: str
    kind: str


class CueRequest(BaseModel):
    path: str
    duration_ms: int | None = Field(None, gt=0)


class CuePayload(BaseModel):
    index: int = Field(ge=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str

    def to_cue(self) -> SubtitleCue:
        if self.end_ms <= self.start_ms:
            raise ValueError("Thời điểm kết thúc phụ đề phải sau thời điểm bắt đầu.")
        return SubtitleCue(self.index, self.start_ms, self.end_ms, self.text)


class VideoSegmentPayload(BaseModel):
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)

    def to_segment(self) -> EditorVideoSegment:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("Điểm kết thúc đoạn video phải sau điểm bắt đầu.")
        return EditorVideoSegment(self.source_start_ms, self.source_end_ms)


class ExportRequest(BaseModel):
    video_path: str
    output_dir: str
    project_name: str = ""
    audio_path: str | None = None
    cues: list[CuePayload] = Field(default_factory=list)
    segments: list[VideoSegmentPayload] = Field(default_factory=list)
    audio_offset_ms: int = Field(0, ge=0)
    audio_mode: str = "mix"
    source_volume: int = Field(100, ge=0, le=200)
    external_volume: int = Field(100, ge=0, le=200)
    resolution: str = "original"
    fps: str = "source"
    encoder: str = "auto"
    quality: int = Field(20, ge=14, le=32)
    subtitle_font_size: int = Field(22, ge=10, le=72)
    subtitle_margin: int = Field(36, ge=0, le=500)


def _existing_file(raw_path: str, label: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise HTTPException(status_code=422, detail=f"{label} không tồn tại.")
    return path


def _register_source(path: Path) -> tuple[str, str]:
    source_id = uuid.uuid4().hex
    with _sources_lock:
        _sources[source_id] = path
        _source_order.append(source_id)
        while len(_source_order) > _MAX_REGISTERED_SOURCES:
            _sources.pop(_source_order.popleft(), None)
    return source_id, f"/api/editor/source/{source_id}"


def _progress(record: TaskRecord):
    def report(message: str) -> None:
        event_bus.emit({"type": "progress", "task_id": record.task_id, "message": message})

    return report


@router.post("/load")
def load_media(body: LoadRequest) -> dict[str, Any]:
    kind = body.kind.strip().lower()
    if kind not in {"video", "audio"}:
        raise HTTPException(status_code=422, detail="Loại media phải là video hoặc audio.")
    path = _existing_file(body.path, "Tệp media")
    try:
        if kind == "video":
            info = probe_editor_media(path)
            payload = {
                "duration_seconds": info.duration_seconds,
                "width": info.width,
                "height": info.height,
                "fps": info.fps,
                "has_audio": info.has_audio,
            }
        else:
            payload = {
                "duration_seconds": probe_audio_duration(path),
                "width": 0,
                "height": 0,
                "fps": 0,
                "has_audio": True,
            }
    except RuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    source_id, url = _register_source(path)
    return {"source_id": source_id, "url": url, "name": path.name, "path": str(path), "kind": kind, **payload}


@router.get("/source/{source_id}")
def stream_source(source_id: str) -> FileResponse:
    with _sources_lock:
        path = _sources.get(source_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Nguồn media không còn khả dụng.")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


@router.post("/cues")
def parse_cues(body: CueRequest) -> dict[str, Any]:
    path = _existing_file(body.path, "Tệp SRT")
    try:
        cues = load_editor_subtitles(path, body.duration_ms)
    except (RuntimeError, UnicodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "name": path.name,
        "path": str(path),
        "cues": [
            {"index": cue.index, "start_ms": cue.start_ms, "end_ms": cue.end_ms, "text": cue.text}
            for cue in cues
        ],
    }


@router.post("/export")
def start_export(body: ExportRequest) -> dict[str, str]:
    video_path = _existing_file(body.video_path, "Video đầu vào")
    audio_path = _existing_file(body.audio_path, "Audio đầu vào") if body.audio_path else None
    if not body.output_dir.strip():
        raise HTTPException(status_code=422, detail="Chọn thư mục xuất trước khi dựng video.")
    if body.resolution not in EDITOR_RESOLUTIONS or body.fps not in EDITOR_FPS_OPTIONS:
        raise HTTPException(status_code=422, detail="Thiết lập hình ảnh không hợp lệ.")
    if body.encoder not in EDITOR_ENCODERS or body.audio_mode not in EDITOR_AUDIO_MODES:
        raise HTTPException(status_code=422, detail="Thiết lập xuất video không hợp lệ.")
    try:
        cues = tuple(item.to_cue() for item in body.cues)
        segments = tuple(item.to_segment() for item in body.segments)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    options = EditorExportOptions(
        video_path=video_path,
        output_dir=Path(body.output_dir).expanduser(),
        project_name=body.project_name,
        audio_path=audio_path,
        subtitle_cues=cues,
        video_segments=segments,
        audio_offset_ms=body.audio_offset_ms,
        audio_mode=body.audio_mode,
        source_volume=body.source_volume,
        external_volume=body.external_volume,
        resolution=body.resolution,
        fps=body.fps,
        encoder=body.encoder,
        quality=body.quality,
        subtitle_font_size=body.subtitle_font_size,
        subtitle_margin=body.subtitle_margin,
    )
    record = task_registry.create(
        "video-editor",
        capability_id="media.ffmpeg",
        resource_keys=resource_keys_for_device(
            "cuda" if "nvenc" in body.encoder.lower() else "cpu"
        ),
    )
    record.on_cancel = lambda: managed_media_processes.terminate_task(record.task_id)

    def run_export():
        from ...video_editor.service import export_editor_video

        return export_editor_video(
            options,
            progress=_progress(record),
            cancellation=record.stop_event,
            task_id=record.task_id,
        )

    def serialize(result: Any) -> dict[str, Any]:
        return {
            "project_dir": str(result.project_dir),
            "video_path": str(result.video_path),
            "video_url": f"/api/files/task/{record.task_id}/{result.video_path.name}",
            "subtitle_path": str(result.subtitle_path) if result.subtitle_path else None,
            "manifest_path": str(result.manifest_path),
            "warnings": list(result.warnings),
        }

    run_task(record, run_export, serialize)
    return {"task_id": record.task_id}


def reset_editor_sources() -> None:
    with _sources_lock:
        _sources.clear()
        _source_order.clear()
