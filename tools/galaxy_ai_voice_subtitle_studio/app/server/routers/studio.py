"""Thin HTTP adapter for Galaxy's engine-neutral single-script Studio."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...common.config import default_config_path, load_app_config
from ...omnivoice.client import OmniVoiceWorkerClient
from ...omnivoice.runtime import OmniVoiceRuntime
from ...omnivoice.task_runner import shared_omnivoice_task_coordinator
from ...omnivoice.worker_pool import get_shared_worker_client
from ...project_graph.integrations import register_studio_take
from ...project_graph.runtime import project_graph_service
from ...runtime.resources import resource_keys_for_device
from ...studio.models import StudioGenerationSpec, StudioTakeView, StudioVoiceSelection
from ...studio.omnivoice_adapter import OmniVoiceStudioAdapter
from ...studio.repository import StudioTakeRepository
from ...studio.service import StudioService
from ..event_bus import event_bus
from ..tasks import TaskRecord, run_task, task_registry


router = APIRouter(prefix="/api/studio", tags=["studio"])
_task_coordinator = shared_omnivoice_task_coordinator


def _runtime() -> OmniVoiceRuntime:
    return OmniVoiceRuntime.default()


def _worker_client() -> OmniVoiceWorkerClient:
    worker_path = Path(__file__).resolve().parents[2] / "omnivoice" / "worker.py"
    return get_shared_worker_client(_runtime(), worker_path)


def _settings_path(request: Request) -> Path:
    path = getattr(request.app.state, "settings_path", None)
    return Path(path) if path is not None else default_config_path()


def _repository(request: Request) -> StudioTakeRepository:
    return StudioTakeRepository(_settings_path(request).with_name("studio_takes.json"))


def _progress(record: TaskRecord):
    def report(message: str) -> None:
        task_registry.report(record.task_id, message)

    return report


class VoiceRequest(BaseModel):
    source: str = "auto"
    profile_id: str = ""
    reference_audio: str = ""
    reference_text: str = ""
    save_profile_name: str = ""
    instruction: str = ""
    consent_confirmed: bool = False
    consent_basis: str = ""
    consent_statement: str = ""


class EngineOptionsRequest(BaseModel):
    num_step: int = Field(default=32, ge=4, le=64)
    guidance_scale: float = Field(default=2.0, ge=0, le=4)
    t_shift: float = Field(default=0.1, ge=0.01, le=1)
    denoise: bool = True
    normalize_text: bool = False
    preprocess_prompt: bool = True
    postprocess_output: bool = True


class GenerationRequest(BaseModel):
    project_id: str = ""
    title: str = "Bản đọc"
    text: str = ""
    engine_id: str = "omnivoice"
    language: str = "vi"
    output_dir: str = ""
    output_name: str = "studio-take"
    model_id: str = "k2-fsa/OmniVoice"
    device: str = "auto"
    speed: float = 1.0
    duration: float | None = None
    formats: list[str] = Field(default_factory=lambda: ["wav", "mp3"])
    voice: VoiceRequest = Field(default_factory=VoiceRequest)
    engine_options: EngineOptionsRequest = Field(default_factory=EngineOptionsRequest)


class BooleanRequest(BaseModel):
    starred: bool | None = None
    primary: bool | None = None


def _spec(body: GenerationRequest, request: Request) -> StudioGenerationSpec:
    config = load_app_config(_settings_path(request))
    output_dir = body.output_dir.strip() or str(
        getattr(config, "omnivoice_output_dir", "") or getattr(config, "output_dir", ".") or "."
    )
    title = body.title.strip() or body.output_name.strip() or "Bản đọc"
    return StudioGenerationSpec(
        project_id=body.project_id.strip(),
        title=title,
        text=body.text,
        engine_id=body.engine_id.strip() or "omnivoice",
        language=body.language.strip() or "vi",
        output_dir=output_dir,
        output_name=body.output_name.strip() or title,
        model_id=body.model_id.strip() or "k2-fsa/OmniVoice",
        device=body.device.strip() or "auto",
        speed=body.speed,
        duration=body.duration,
        formats=tuple(dict.fromkeys(body.formats)),
        voice=StudioVoiceSelection(**body.voice.model_dump()),
        engine_options=body.engine_options.model_dump(),
    )


def _start(request: Request, spec: StudioGenerationSpec, *, rerun_of: str = "") -> dict[str, str]:
    try:
        spec.validate()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    record = task_registry.create(
        "studio-generate",
        capability_id="tts.omnivoice",
        project_id=spec.project_id,
        resource_keys=resource_keys_for_device(spec.device),
    )
    record.on_cancel = lambda: _task_coordinator.cancel(record.task_id)
    repository = _repository(request)
    graph_service = project_graph_service(_settings_path(request))

    def execute() -> dict[str, Any]:
        if spec.engine_id != "omnivoice":
            raise ValueError(f"Engine Studio chưa được cài: {spec.engine_id}")
        take = _task_coordinator.run(
            record.task_id,
            record.stop_event,
            lambda client: StudioService(repository).generate(
                spec,
                OmniVoiceStudioAdapter(client, _runtime().profiles_dir),
                progress=_progress(record),
                rerun_of=rerun_of,
                generation_run_id=record.task_id,
            ),
            client_factory=_worker_client,
        )
        register_studio_take(graph_service, take)
        event_bus.emit({"type": "event", "kind": "studio_takes_updated", "payload": {}})
        return {"take": _take_dict(take)}

    run_task(record, execute)
    return {"task_id": record.task_id}


@router.post("/generations")
def generate(body: GenerationRequest, request: Request) -> dict[str, str]:
    return _start(request, _spec(body, request))


@router.get("/takes")
def list_takes(
    request: Request,
    project_id: str = "",
    query: str = "",
    starred_only: bool = False,
) -> list[dict[str, Any]]:
    return [
        _take_dict(item)
        for item in _repository(request).list(
            project_id=project_id, query=query, starred_only=starred_only
        )
    ]


@router.patch("/takes/{take_id}/starred")
def set_starred(take_id: str, body: BooleanRequest, request: Request) -> dict[str, Any]:
    try:
        return _take_dict(_repository(request).set_starred(take_id, bool(body.starred)))
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản đọc")


@router.patch("/takes/{take_id}/primary")
def set_primary(take_id: str, body: BooleanRequest, request: Request) -> dict[str, Any]:
    try:
        take = _repository(request).set_primary(take_id, bool(body.primary))
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản đọc")
    event_bus.emit({"type": "event", "kind": "studio_primary_updated", "payload": {}})
    return _take_dict(take)


@router.post("/takes/{take_id}/rerun")
def rerun(take_id: str, request: Request) -> dict[str, str]:
    view = _repository(request).get(take_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản đọc")
    return _start(request, view.take.spec, rerun_of=view.take.take_id)


@router.delete("/takes/{take_id}")
def delete_take(take_id: str, request: Request) -> dict[str, bool]:
    _repository(request).delete(take_id)
    event_bus.emit({"type": "event", "kind": "studio_takes_updated", "payload": {}})
    return {"ok": True}


@router.get("/takes/{take_id}/audio")
def take_audio(
    take_id: str,
    request: Request,
    audio_format: str = Query(default="", alias="format"),
    download: bool = False,
) -> FileResponse:
    repository = _repository(request)
    if repository.get(take_id) is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản đọc")
    try:
        path = repository.resolve_audio(take_id, audio_format)
    except (KeyError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="File âm thanh không còn tồn tại")
    media_type = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/takes/{take_id}/handoff")
def handoff(take_id: str, request: Request) -> dict[str, Any]:
    view = _repository(request).get(take_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản đọc")
    take = view.take
    return {
        "schema_version": 1,
        "kind": "studio_take",
        "project_id": take.project_id,
        "generation_run": _take_dict(view),
        "primary_audio": take.preview_path,
        "voice_profile_id": take.profile_id or take.spec.voice.profile_id,
    }


def _take_dict(view: StudioTakeView) -> dict[str, Any]:
    take = view.take
    return {
        "take_id": take.take_id,
        "project_id": take.project_id,
        "title": take.title,
        "engine_id": take.engine_id,
        "text": take.spec.text,
        "language": take.spec.language,
        "voice_source": take.spec.voice.source,
        "voice_profile_id": take.spec.voice.profile_id,
        "speed": take.spec.speed,
        "formats": list(take.spec.formats),
        "project_dir": take.project_dir,
        "wav_path": take.wav_path,
        "mp3_path": take.mp3_path or None,
        "manifest_path": take.manifest_path,
        "profile_id": take.profile_id,
        "warnings": list(take.warnings),
        "starred": view.starred,
        "primary": view.primary,
        "generation_run_id": take.generation_run_id,
        "rerun_of": take.rerun_of,
        "created_at": take.created_at,
        "audio_url": f"/api/studio/takes/{take.take_id}/audio",
    }
