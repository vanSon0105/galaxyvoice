"""Thin HTTP adapter for the shared audio postproduction contract."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...audio_postproduction.models import (
    AudioExportRequest,
    AudioPostChain,
    AudioSource,
    ExportMetadata,
    SegmentGain,
)
from ...audio_postproduction.service import AudioPostproductionService
from ...common.processes import managed_media_processes
from ..tasks import run_task, task_registry


router = APIRouter(prefix="/api/audio-post", tags=["audio-postproduction"])


def _service() -> AudioPostproductionService:
    return AudioPostproductionService()


class WaveformRequest(BaseModel):
    source_path: str
    project_dir: str
    points: int = Field(default=256, ge=16, le=2_048)


class SourceRequest(BaseModel):
    source_id: str
    path: str
    role: str = "voice"
    selected: bool = True
    gain_db: float = Field(default=0.0, ge=-60, le=24)


class SegmentGainRequest(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    gain_db: float = Field(ge=-60, le=24)


class PostChainRequest(BaseModel):
    trim_start_ms: int = Field(default=0, ge=0)
    trim_end_ms: int | None = Field(default=None, gt=0)
    gain_db: float = Field(default=0.0, ge=-60, le=24)
    segment_gains: list[SegmentGainRequest] = Field(default_factory=list)
    fade_in_ms: int = Field(default=0, ge=0)
    fade_out_ms: int = Field(default=0, ge=0)
    normalize: bool = False
    target_lufs: float = Field(default=-16.0, ge=-36, le=-5)
    true_peak_db: float = Field(default=-1.0, ge=-9, le=0)
    loudness_range: float = Field(default=11.0, ge=1, le=30)
    preset: str = "none"
    trim_silence: bool = False


class MetadataRequest(BaseModel):
    title: str = ""
    artist: str = ""
    album: str = ""
    comment: str = ""


class ExportRequest(BaseModel):
    project_id: str
    workflow_id: str
    workspace: str
    project_dir: str
    title: str = "audio-export"
    sources: list[SourceRequest]
    formats: list[str] = Field(default_factory=lambda: ["wav"])
    chain: PostChainRequest = Field(default_factory=PostChainRequest)
    metadata: MetadataRequest = Field(default_factory=MetadataRequest)
    sample_rate: int = Field(default=48_000, ge=8_000, le=192_000)
    channels: int = Field(default=2, ge=1, le=2)
    bitrate_kbps: int = Field(default=192, ge=64, le=512)


@router.post("/waveform")
def waveform(body: WaveformRequest) -> dict[str, Any]:
    try:
        result = _service().waveform(
            Path(body.source_path), project_dir=Path(body.project_dir), points=body.points
        )
    except (ValueError, OSError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"duration_ms": result.duration_ms, "peaks": list(result.peaks)}


@router.get("/sources")
def discover_sources(project_dir: str = Query(min_length=1)) -> list[dict[str, object]]:
    try:
        sources = _service().discover_sources(Path(project_dir))
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return [
        {
            "source_id": source.source_id,
            "label": source.path.name,
            "path": str(source.path),
            "role": source.role,
            "selected": False,
            "gain_db": source.gain_db,
        }
        for source in sources
    ]


@router.post("/exports")
def export_audio(body: ExportRequest) -> dict[str, str]:
    chain_data = body.chain.model_dump(exclude={"segment_gains"})
    request = AudioExportRequest(
        project_id=body.project_id,
        workflow_id=body.workflow_id,
        workspace=body.workspace,
        project_dir=Path(body.project_dir),
        title=body.title,
        sources=tuple(
            AudioSource(
                item.source_id, Path(item.path), role=item.role,
                selected=item.selected, gain_db=item.gain_db,
            )
            for item in body.sources
        ),
        formats=tuple(body.formats),
        chain=AudioPostChain(
            **chain_data,
            segment_gains=tuple(SegmentGain(**item.model_dump()) for item in body.chain.segment_gains),
        ),
        metadata=ExportMetadata(**body.metadata.model_dump()),
        sample_rate=body.sample_rate,
        channels=body.channels,
        bitrate_kbps=body.bitrate_kbps,
    )
    record = task_registry.create(
        "audio-post-export",
        capability_id="media.ffmpeg",
        project_id=body.project_id,
        workflow_id=body.workflow_id,
        resource_keys=("cpu",),
        recovery_route={
            "batch": "/voice/batch",
            "dubbing": "/voice/dubbing",
            "longform": "/voice/longform",
            "stories": "/voice/longform",
            "audiobook": "/voice/longform",
        }.get(body.workspace.casefold(), "/voice"),
    )
    record.on_cancel = lambda: managed_media_processes.terminate_task(record.task_id)

    def execute():
        return _service().export(
            request,
            progress=lambda message, value: task_registry.report(
                record.task_id, message, progress=value
            ),
            stop_event=record.stop_event,
            task_id=record.task_id,
        )

    run_task(record, execute, _result_payload)
    return {"task_id": record.task_id}


def _result_payload(result) -> dict[str, Any]:
    media_urls = {
        name: (
            f"/api/audio-post/exports/{result.export_id}/media/{name}"
            f"?project_dir={quote(result.project_dir.as_posix(), safe='')}"
        )
        for name in result.files
    }
    return {
        "export_id": result.export_id,
        "project_dir": str(result.project_dir),
        "files": {name: str(path) for name, path in result.files.items()},
        "manifest_path": str(result.manifest_path),
        "media_urls": media_urls,
        "warnings": list(result.warnings),
    }


@router.get("/exports")
def list_exports(project_dir: str = Query(min_length=1)) -> list[dict[str, object]]:
    try:
        return _service().list_exports(Path(project_dir))
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/exports/{export_id}/media/{format_name}")
def export_media(
    export_id: str,
    format_name: str,
    project_dir: str = Query(min_length=1),
    download: bool = False,
) -> FileResponse:
    try:
        path = _service().resolve_export(Path(project_dir), export_id, format_name)
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, filename=path.name if download else None)
