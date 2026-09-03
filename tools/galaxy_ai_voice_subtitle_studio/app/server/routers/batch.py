"""HTTP adapter for Galaxy's native Batch synthesis workflow."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...batch.models import BatchItemSpec, BatchRun, BatchSpec
from ...batch.omnivoice_adapter import OmniVoiceBatchAdapter
from ...batch.parser import parse_batch_source, validate_batch_items
from ...batch.repository import BatchRepository
from ...batch.service import BatchService
from ...batch.system_voice_adapter import SystemVoiceBatchAdapter
from ...common.config import default_config_path, load_app_config
from ...omnivoice.client import OmniVoiceWorkerClient
from ...omnivoice.runtime import OmniVoiceRuntime
from ...omnivoice.task_runner import shared_omnivoice_task_coordinator
from ...omnivoice.worker_pool import get_shared_worker_client
from ...project_graph.integrations import register_batch_run
from ...project_graph.runtime import project_graph_service
from ...runtime.jobs import ACTIVE_STATUSES, TaskContext
from ...runtime.resources import resource_keys_for_device
from ...studio.models import StudioVoiceSelection
from ...voice.tts import EDGE_ENGINE_CODE, create_tts_engine, tts_engine_codes
from ..event_bus import event_bus
from ..tasks import task_registry


router = APIRouter(prefix="/api/batch", tags=["batch"])
_task_coordinator = shared_omnivoice_task_coordinator


class BatchVoiceRequest(BaseModel):
    source: str = "auto"
    profile_id: str = ""
    reference_audio: str = ""
    reference_text: str = ""
    instruction: str = ""


class BatchItemRequest(BaseModel):
    item_id: str = ""
    text: str = ""
    language: str = ""
    speed: float | None = None
    duration: float | None = None
    voice_source: str = ""
    profile_id: str = ""
    instruction: str = ""
    formats: list[str] = Field(default_factory=list)


class ParseRequest(BaseModel):
    source: str = ""
    long_form: bool = False


class CreateBatchRequest(BaseModel):
    project_id: str = ""
    title: str = "Batch"
    output_dir: str = ""
    engine_id: str = "omnivoice"
    model_id: str = "k2-fsa/OmniVoice"
    device: str = "auto"
    language: str = "vi"
    speed: float = 1.0
    duration: float | None = None
    formats: list[str] = Field(default_factory=lambda: ["wav", "mp3"])
    voice: BatchVoiceRequest = Field(default_factory=BatchVoiceRequest)
    engine_options: dict[str, Any] = Field(default_factory=dict)
    combine: bool = False
    gap_ms: int = 250
    items: list[BatchItemRequest] = Field(default_factory=list)


def _runtime() -> OmniVoiceRuntime:
    return OmniVoiceRuntime.default()


def _worker_client() -> OmniVoiceWorkerClient:
    worker_path = Path(__file__).resolve().parents[2] / "omnivoice" / "worker.py"
    return get_shared_worker_client(_runtime(), worker_path)


def _settings_path(request: Request) -> Path:
    path = getattr(request.app.state, "settings_path", None)
    return Path(path) if path is not None else default_config_path()


def _repository(request: Request) -> BatchRepository:
    repository = BatchRepository(_settings_path(request).with_name("batch_runs.json"))
    active = {
        str(item["task_id"])
        for item in task_registry.snapshot()
        if item.get("status") in ACTIVE_STATUSES
    }
    repository.recover_stale(active)
    return repository


def _batch_spec(body: CreateBatchRequest, request: Request) -> BatchSpec:
    config = load_app_config(_settings_path(request))
    output_dir = body.output_dir.strip() or str(
        getattr(config, "omnivoice_output_dir", "") or getattr(config, "output_dir", ".") or "."
    )
    return BatchSpec(
        project_id=body.project_id.strip(),
        title=body.title.strip() or "Batch",
        output_dir=output_dir,
        engine_id=body.engine_id.strip() or "omnivoice",
        model_id=body.model_id.strip() or "k2-fsa/OmniVoice",
        device=body.device.strip() or "auto",
        language=body.language.strip() or "vi",
        speed=body.speed,
        duration=body.duration,
        formats=tuple(dict.fromkeys(value.lower() for value in body.formats)),
        voice=StudioVoiceSelection(**body.voice.model_dump()),
        engine_options=dict(body.engine_options),
        combine=body.combine,
        gap_ms=body.gap_ms,
    )


def _batch_items(body: CreateBatchRequest) -> tuple[BatchItemSpec, ...]:
    return validate_batch_items(
        [
            BatchItemSpec(
                item_id=item.item_id.strip(),
                text=item.text,
                language=item.language.strip(),
                speed=item.speed,
                duration=item.duration,
                voice_source=item.voice_source.strip(),
                profile_id=item.profile_id.strip(),
                instruction=item.instruction,
                formats=tuple(value.lower() for value in item.formats),
            )
            for item in body.items
        ]
    )


def _start(request: Request, run: BatchRun) -> dict[str, str]:
    is_omnivoice = run.spec.engine_id == "omnivoice"
    is_system_voice = run.spec.engine_id in tts_engine_codes()
    resource_keys = resource_keys_for_device(run.spec.device) if is_omnivoice else (("network",) if run.spec.engine_id == EDGE_ENGINE_CODE else ())
    record = task_registry.create(
        "voice-batch",
        capability_id=f"tts.{run.spec.engine_id}",
        pausable=True,
        project_id=run.spec.project_id,
        workflow_id=run.batch_id,
        resource_keys=resource_keys,
    )
    if is_omnivoice:
        record.on_cancel = lambda: _task_coordinator.cancel(record.task_id)
    repository = _repository(request)
    graph_service = project_graph_service(_settings_path(request))
    repository.set_task(run.batch_id, record.task_id)

    def operation(context: TaskContext) -> BatchRun:
        if is_omnivoice:
            return _task_coordinator.run(
                record.task_id,
                record.stop_event,
                lambda client: BatchService(repository).execute(
                    run.batch_id,
                    OmniVoiceBatchAdapter(client, _runtime().profiles_dir),
                    task_id=record.task_id,
                    progress=lambda message, value: context.report(message, progress=value),
                    checkpoint=context.save_checkpoint,
                    control=context.wait_if_paused,
                    stop_event=record.stop_event,
                ),
                client_factory=_worker_client,
            )
        if is_system_voice:
            return BatchService(repository).execute(
                run.batch_id,
                SystemVoiceBatchAdapter(
                    create_tts_engine(run.spec.engine_id),
                    str(run.spec.engine_options.get("voice_name") or ""),
                ),
                task_id=record.task_id,
                progress=lambda message, value: context.report(message, progress=value),
                checkpoint=context.save_checkpoint,
                control=context.wait_if_paused,
                stop_event=record.stop_event,
            )
        raise ValueError(f"Engine Batch chưa được cài: {run.spec.engine_id}")

    def serialize(completed: BatchRun) -> dict[str, Any]:
        register_batch_run(graph_service, completed)
        return _run_dict(completed)

    task_registry.submit(record, operation, serialize)
    event_bus.emit(
        {"type": "event", "kind": "batch_run_started", "payload": {"batch_id": run.batch_id}}
    )
    return {"batch_id": run.batch_id, "task_id": record.task_id}


@router.post("/parse")
def parse(body: ParseRequest) -> list[dict[str, Any]]:
    try:
        return [item.to_payload() for item in parse_batch_source(body.source, long_form=body.long_form)]
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/runs")
def create_run(body: CreateBatchRequest, request: Request) -> dict[str, str]:
    try:
        spec = _batch_spec(body, request)
        spec.validate()
        items = _batch_items(body)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    run = _repository(request).create(spec, items)
    return _start(request, run)


@router.get("/runs")
def list_runs(request: Request, project_id: str = "") -> list[dict[str, Any]]:
    return [_run_dict(run) for run in _repository(request).list(project_id=project_id)]


@router.get("/runs/{batch_id}")
def get_run(batch_id: str, request: Request) -> dict[str, Any]:
    run = _repository(request).get(batch_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy Batch")
    return _run_dict(run)


@router.post("/runs/{batch_id}/resume")
def resume_run(batch_id: str, request: Request) -> dict[str, str]:
    try:
        run = _repository(request).prepare_resume(batch_id, retry_failed=False)
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy Batch")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return _start(request, run)


@router.post("/runs/{batch_id}/retry")
def retry_run(batch_id: str, request: Request) -> dict[str, str]:
    try:
        run = _repository(request).prepare_resume(batch_id, retry_failed=True)
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy Batch")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return _start(request, run)


@router.get("/runs/{batch_id}/manifest")
def manifest(batch_id: str, request: Request) -> FileResponse:
    return _file_response(_repository(request), batch_id, "manifest", download=True)


@router.get("/runs/{batch_id}/audio")
def combined_audio(
    batch_id: str,
    request: Request,
    format: str = "wav",
    download: bool = False,
) -> FileResponse:
    return _file_response(_repository(request), batch_id, format.lower(), download=download)


@router.get("/runs/{batch_id}/items/{item_id}/audio")
def item_audio(
    batch_id: str,
    item_id: str,
    request: Request,
    format: str = "wav",
    download: bool = False,
) -> FileResponse:
    return _file_response(
        _repository(request), batch_id, format.lower(), item_id=item_id, download=download
    )


def _file_response(
    repository: BatchRepository,
    batch_id: str,
    kind: str,
    *,
    item_id: str = "",
    download: bool,
) -> FileResponse:
    if kind not in {"wav", "mp3", "manifest"}:
        raise HTTPException(status_code=422, detail="Định dạng không hợp lệ")
    try:
        path = repository.resolve_artifact(batch_id, kind, item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy Batch hoặc mục Batch")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File Batch không còn tồn tại")
    media_type = (
        "application/json"
        if kind == "manifest"
        else "audio/mpeg"
        if kind == "mp3"
        else "audio/wav"
    )
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


def _run_dict(run: BatchRun) -> dict[str, Any]:
    return {
        "batch_id": run.batch_id,
        "project_id": run.spec.project_id,
        "title": run.spec.title,
        "status": run.status,
        "task_id": run.task_id,
        "engine_id": run.spec.engine_id,
        "language": run.spec.language,
        "formats": list(run.spec.formats),
        "combine": run.spec.combine,
        "gap_ms": run.spec.gap_ms,
        "root_dir": run.root_dir,
        "manifest_path": run.manifest_path,
        "combined_wav_path": run.combined_wav_path or None,
        "combined_mp3_path": run.combined_mp3_path or None,
        "completed_count": run.completed_count,
        "failed_count": run.failed_count,
        "total_count": len(run.items),
        "warnings": run.warnings,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "items": [
            {
                **item.spec.to_payload(),
                "status": item.status,
                "attempts": item.attempts,
                "error": item.error or None,
                "wav_path": item.wav_path or None,
                "mp3_path": item.mp3_path or None,
                "warnings": list(item.warnings),
                "audio_url": (
                    f"/api/batch/runs/{run.batch_id}/items/{item.spec.item_id}/audio"
                    if item.status == "done"
                    else None
                ),
            }
            for item in run.items
        ],
    }
