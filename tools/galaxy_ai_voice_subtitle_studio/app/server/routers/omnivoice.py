"""OmniVoice engine endpoints: runtime status, generation, profiles, batch.

Thin adapter over the shared service modules (app/omnivoice/*). Generation
runs as a task; cancel kills the worker subprocess via the task's on_cancel
hook plus the batch-level stop_event.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...common.config import default_config_path, load_app_config
from ...omnivoice.batch import (
    generate_omnivoice_batch,
    parse_batch_items,
    split_long_form,
)
from ...omnivoice.client import OmniVoiceWorkerClient
from ...omnivoice.features import (
    ACCENT_CHOICES,
    AGE_CHOICES,
    COMMON_LANGUAGES,
    DIALECT_CHOICES,
    GENDER_CHOICES,
    PITCH_CHOICES,
    STYLE_CHOICES,
)
from ...omnivoice.models import (
    AUTO_MODE,
    DEFAULT_MODEL_ID,
    OMNIVOICE_MODES,
    OmniVoiceGenerationOptions,
)
from ...omnivoice.profiles import (
    delete_voice_profile,
    find_voice_profile,
    list_voice_profiles,
)
from ...omnivoice.runtime import (
    OMNIVOICE_DEVICES,
    OmniVoiceRuntime,
    inspect_runtime,
    load_supported_language_ids,
    omnivoice_device_label,
)
from ...omnivoice.service import generate_omnivoice_audio
from ..event_bus import event_bus
from ..tasks import TaskRecord, run_task, task_registry

router = APIRouter(prefix="/api/omnivoice")

STATUS_CACHE_TTL_SECONDS = 60.0
_status_cache: dict[str, Any] = {"at": 0.0, "value": None}
_client: OmniVoiceWorkerClient | None = None
_client_lock = threading.Lock()


def _runtime() -> OmniVoiceRuntime:
    return OmniVoiceRuntime.default()


def _worker_client() -> OmniVoiceWorkerClient:
    global _client
    with _client_lock:
        if _client is None:
            worker_path = Path(__file__).resolve().parents[1] / "omnivoice" / "worker.py"
            _client = OmniVoiceWorkerClient(_runtime(), worker_path)
        return _client


def _config() -> Any:
    return load_app_config(default_config_path())


class GenerateRequest(BaseModel):
    mode: str = AUTO_MODE
    text: str = ""
    output_dir: str = ""
    project_name: str = "omnivoice"
    model_id: str = DEFAULT_MODEL_ID
    device: str = "auto"
    language: str = "vi"
    reference_audio: str = ""
    reference_text: str = ""
    profile_id: str = ""
    save_profile_name: str = ""
    instruct: str = ""
    num_step: int = 32
    guidance_scale: float = 2.0
    t_shift: float = 0.1
    layer_penalty_factor: float = 5.0
    position_temperature: float = 5.0
    class_temperature: float = 0.0
    speed: float = 1.0
    duration: float | None = None
    denoise: bool = True
    normalize_text: bool = False
    preprocess_prompt: bool = True
    postprocess_output: bool = True
    audio_chunk_duration: float = 15.0
    audio_chunk_threshold: float = 30.0
    pad_duration: float = 0.0
    fade_duration: float = 0.02
    export_mp3: bool = True
    enable_flashinfer: bool = False
    flashinfer_cuda_graph: bool = True
    lora_adapter: str = ""


class BatchRequest(BaseModel):
    source: str = ""
    long_form: bool = False
    combine: bool = False
    gap_ms: int = 250
    mode: str = AUTO_MODE
    output_dir: str = ""
    project_name: str = "omnivoice-batch"
    model_id: str = DEFAULT_MODEL_ID
    device: str = "auto"
    language: str = "vi"
    speed: float = 1.0
    duration: float | None = None
    export_mp3: bool = True


def _options_from(request: GenerateRequest, config: Any) -> OmniVoiceGenerationOptions:
    config_value = lambda key, default: (  # noqa: E731
        getattr(config, key, None) or default
    )
    return OmniVoiceGenerationOptions(
        mode=request.mode,
        text=request.text,
        output_dir=Path(request.output_dir or config_value("omnivoice_output_dir", ".")).expanduser(),
        project_name=request.project_name or "omnivoice",
        model_id=request.model_id or DEFAULT_MODEL_ID,
        device=request.device,
        language=request.language,
        reference_audio=Path(request.reference_audio).expanduser() if request.reference_audio else None,
        reference_text=request.reference_text,
        profile_id=request.profile_id,
        save_profile_name=request.save_profile_name,
        instruct=request.instruct,
        num_step=request.num_step,
        guidance_scale=request.guidance_scale,
        t_shift=request.t_shift,
        layer_penalty_factor=request.layer_penalty_factor,
        position_temperature=request.position_temperature,
        class_temperature=request.class_temperature,
        speed=request.speed,
        duration=request.duration,
        denoise=request.denoise,
        normalize_text=request.normalize_text,
        preprocess_prompt=request.preprocess_prompt,
        postprocess_output=request.postprocess_output,
        audio_chunk_duration=request.audio_chunk_duration,
        audio_chunk_threshold=request.audio_chunk_threshold,
        pad_duration=request.pad_duration,
        fade_duration=request.fade_duration,
        export_mp3=request.export_mp3,
        enable_flashinfer=request.enable_flashinfer,
        flashinfer_cuda_graph=request.flashinfer_cuda_graph,
        lora_adapter=request.lora_adapter,
        profiles_dir=_runtime().profiles_dir,
    )


def _result_dict(result: Any) -> dict[str, Any]:
    return {
        "project_dir": str(result.project_dir),
        "wav_path": str(result.wav_path),
        "mp3_path": str(result.mp3_path) if result.mp3_path else None,
        "manifest_path": str(result.manifest_path),
        "profile_id": result.profile_id,
        "warnings": list(result.warnings),
    }


def _batch_result_dict(result: Any) -> dict[str, Any]:
    return {
        "project_dir": str(result.project_dir),
        "manifest_path": str(result.manifest_path),
        "combined_wav_path": str(result.combined_wav_path) if result.combined_wav_path else None,
        "combined_mp3_path": str(result.combined_mp3_path) if result.combined_mp3_path else None,
        "preview_path": str(result.preview_path) if result.preview_path else None,
        "item_count": len(result.item_results),
        "warnings": list(result.warnings),
    }


def _progress(record: TaskRecord):
    def report(message: str) -> None:
        event_bus.emit({"type": "progress", "task_id": record.task_id, "message": message})

    return report


@router.get("/status")
def status() -> dict[str, Any]:
    now = time.monotonic()
    if _status_cache["value"] is None or now - _status_cache["at"] > STATUS_CACHE_TTL_SECONDS:
        runtime = _runtime()
        inspected = inspect_runtime(runtime)
        languages = load_supported_language_ids(runtime) or COMMON_LANGUAGES
        _status_cache["value"] = {
            "installed": inspected.installed,
            "message": inspected.message,
            "python_path": str(inspected.python_path),
            "languages": list(languages),
            "devices": [
                {"code": code, "label": omnivoice_device_label(code)} for code in OMNIVOICE_DEVICES
            ],
            "design_options": {
                "gender": [{"label": label, "value": value} for label, value in GENDER_CHOICES.items()],
                "age": [{"label": label, "value": value} for label, value in AGE_CHOICES.items()],
                "pitch": [{"label": label, "value": value} for label, value in PITCH_CHOICES.items()],
                "style": [{"label": label, "value": value} for label, value in STYLE_CHOICES.items()],
                "accent": [{"label": label, "value": value} for label, value in ACCENT_CHOICES.items()],
                "dialect": [{"label": label, "value": value} for label, value in DIALECT_CHOICES.items()],
            },
        }
        _status_cache["at"] = now
    return _status_cache["value"]


@router.post("/install")
def install_runtime() -> dict[str, bool]:
    import subprocess

    from ...common.paths import studio_root

    installer = studio_root() / "install_omnivoice.ps1"
    if not installer.is_file():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy bộ cài: {installer}")
    device = _config().omnivoice_device
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(installer),
                "-Device",
                device,
            ],
            cwd=str(studio_root()),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Không mở được bộ cài: {error}")
    event_bus.emit({"type": "event", "kind": "omnivoice_install_started", "payload": {}})
    return {"ok": True}


@router.post("/generate")
def generate(request: GenerateRequest) -> dict[str, Any]:
    if request.mode not in OMNIVOICE_MODES:
        raise HTTPException(status_code=422, detail=f"Chế độ OmniVoice không hợp lệ: {request.mode}")
    if not request.text.strip():
        raise HTTPException(status_code=422, detail="Hãy nhập nội dung cần tạo giọng.")
    options = _options_from(request, _config())
    record = task_registry.create("omnivoice-generate")
    record.on_cancel = _worker_client().stop
    event_bus.emit({"type": "task", "task_id": record.task_id, "status": "running"})
    run_task(
        record,
        lambda: generate_omnivoice_audio(
            options,
            _worker_client(),
            progress=_progress(record),
        ),
        _result_dict,
    )
    return {"task_id": record.task_id}


@router.post("/batch")
def batch(request: BatchRequest) -> dict[str, Any]:
    if request.mode not in OMNIVOICE_MODES:
        raise HTTPException(status_code=422, detail=f"Chế độ OmniVoice không hợp lệ: {request.mode}")
    try:
        items = split_long_form(request.source) if request.long_form else parse_batch_items(request.source)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    config = _config()
    base_options = _options_from(
        GenerateRequest(
            mode=request.mode,
            text="",
            output_dir=request.output_dir or getattr(config, "omnivoice_output_dir", ""),
            project_name=request.project_name,
            model_id=request.model_id,
            device=request.device,
            language=request.language,
            speed=request.speed,
            duration=request.duration,
            export_mp3=request.export_mp3,
        ),
        config,
    )
    record = task_registry.create("omnivoice-batch")
    record.on_cancel = _worker_client().stop
    event_bus.emit({"type": "task", "task_id": record.task_id, "status": "running"})
    run_task(
        record,
        lambda: generate_omnivoice_batch(
            base_options,
            items,
            _worker_client(),
            combine=request.combine,
            gap_ms=request.gap_ms,
            progress=_progress(record),
            stop_event=record.stop_event,
        ),
        _batch_result_dict,
    )
    return {"task_id": record.task_id}


@router.get("/profiles")
def profiles() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile.profile_id,
            "display_name": profile.display_name,
            "language": profile.language,
            "created_at": profile.created_at,
            "reference_text": profile.reference_text,
            "has_reference_audio": profile.reference_audio_path is not None,
        }
        for profile in list_voice_profiles(_runtime().profiles_dir)
    ]


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: str) -> dict[str, bool]:
    runtime = _runtime()
    if find_voice_profile(runtime.profiles_dir, profile_id) is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy profile giọng")
    try:
        delete_voice_profile(runtime.profiles_dir, profile_id)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=500, detail=f"Không xóa được profile: {error}")
    event_bus.emit(
        {"type": "event", "kind": "omnivoice_profiles_updated", "payload": {"profile_id": profile_id}}
    )
    return {"ok": True}
