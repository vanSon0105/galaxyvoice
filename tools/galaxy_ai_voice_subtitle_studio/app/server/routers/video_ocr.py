"""Thin HTTP boundary for editor-native burned-in subtitle OCR."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...common.paths import studio_root
from ...common.processes import managed_media_processes
from ...project_graph.runtime import project_graph_service
from ...video_ocr import (
    OCR_FAST_MODE,
    VideoOcrOptions,
    VideoOcrRegion,
    default_video_ocr_runtime,
    install_video_ocr_runtime,
    recognize_burned_subtitles,
    register_video_ocr_result,
)
from ..tasks import TaskRecord, run_task, task_registry

router = APIRouter(prefix="/api/editor/ocr", tags=["video-ocr"])


class OcrRegionRequest(BaseModel):
    x: int = Field(5, ge=0, le=99)
    y: int = Field(68, ge=0, le=99)
    width: int = Field(90, ge=1, le=100)
    height: int = Field(27, ge=1, le=100)

    def to_region(self) -> VideoOcrRegion:
        region = VideoOcrRegion(self.x, self.y, self.width, self.height)
        region.validate()
        return region


class VideoOcrRequest(BaseModel):
    galaxy_project_id: str = ""
    video_path: str
    output_dir: str
    project_name: str = ""
    mode: str = OCR_FAST_MODE
    language: str = "vi"
    region: OcrRegionRequest = Field(default_factory=OcrRegionRequest)


def _progress(record: TaskRecord):
    return lambda message: task_registry.report(record.task_id, message)


@router.get("/meta")
def get_ocr_meta() -> dict[str, object]:
    runtime = default_video_ocr_runtime()
    return {
        "runtime_ready": runtime.ready,
        "runtime_path": str(runtime.python_path) if runtime.ready else "",
        "installer_available": (studio_root() / "install_video_ocr.ps1").is_file(),
        "modes": [
            {"code": "fast", "label": "Nhanh", "sample_fps": 2},
            {"code": "accurate", "label": "Chinh xac", "sample_fps": 4},
        ],
    }


@router.post("/install")
def install_ocr() -> dict[str, str]:
    installer = studio_root() / "install_video_ocr.ps1"
    if not installer.is_file():
        raise HTTPException(status_code=404, detail=f"Khong tim thay bo cai OCR: {installer}")
    record = task_registry.create(
        "video-ocr-install",
        capability_id="video.ocr",
        resource_keys=("network", "disk"),
        recovery_route="/editor",
    )
    record.on_cancel = lambda: managed_media_processes.terminate_task(record.task_id)

    def operation() -> dict[str, str]:
        return install_video_ocr_runtime(
            installer,
            progress=_progress(record),
            stop_event=record.stop_event,
            task_id=record.task_id,
        )

    run_task(record, operation, lambda result: result)
    return {"task_id": record.task_id}


@router.post("/recognize")
def start_ocr(body: VideoOcrRequest, request: Request) -> dict[str, str]:
    if not body.output_dir.strip():
        raise HTTPException(status_code=422, detail="Chon thu muc xuat truoc khi nhan dang OCR.")
    video_path = Path(body.video_path).expanduser().resolve()
    try:
        options = VideoOcrOptions(
            video_path=video_path,
            output_dir=Path(body.output_dir).expanduser(),
            project_name=body.project_name,
            mode=body.mode,
            region=body.region.to_region(),
            language=body.language.strip() or "vi",
        )
        options.validate()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not default_video_ocr_runtime().ready:
        raise HTTPException(status_code=409, detail="Runtime OCR local chua duoc cai.")

    record = task_registry.create(
        "editor-video-ocr",
        capability_id="video.ocr",
        resource_keys=("cpu-ocr",),
        project_id=body.galaxy_project_id.strip(),
        recovery_route="/editor",
        recovery_hint="Mo Dung video va chay lai nhan dang phu de chay.",
    )
    record.on_cancel = lambda: managed_media_processes.terminate_task(record.task_id)
    configured = getattr(request.app.state, "settings_path", None)
    graph_service = project_graph_service(Path(configured) if configured is not None else None)

    def operation():
        result = recognize_burned_subtitles(
            options,
            progress=_progress(record),
            stop_event=record.stop_event,
            task_id=record.task_id,
        )
        register_video_ocr_result(
            graph_service,
            result,
            project_id=body.galaxy_project_id,
            owner_id=record.task_id,
            label=body.project_name or video_path.stem,
            mode=body.mode,
        )
        return result

    def serialize(result):
        return result.to_payload()

    run_task(record, operation, serialize)
    return {"task_id": record.task_id}
