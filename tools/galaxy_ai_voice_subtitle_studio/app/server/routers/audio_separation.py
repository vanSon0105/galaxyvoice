"""Web API for the local Ultimate Vocal Remover audio workspace."""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...audio_separation.service import (
    AUDIO_OUTPUT_FORMATS,
    AUDIO_PRESET_FIELDS,
    AUDIO_PROCESS_METHOD_LABELS,
    AUDIO_PROCESS_METHODS,
    AUDIO_PROCESSING_DEVICE_LABELS,
    AUDIO_PROCESSING_DEVICES,
    AUDIO_SAVED_SETTINGS,
    CPU_AUDIO_DEVICE,
    MDX_METHOD,
    AudioSeparationOptions,
    audio_separator_runtime_ready,
    default_audio_separator_runtime,
    default_managed_audio_models_root,
    default_uvr_root,
    download_audio_model,
    discover_uvr_models,
    list_downloadable_audio_models,
    load_audio_presets,
    normalize_audio_device,
    normalize_audio_method,
    resolve_audio_device,
    save_audio_presets,
    serialize_downloadable_audio_models,
)
from ...common.config import default_config_path
from ...common.paths import studio_root
from ...common.processes import managed_media_processes
from ...project_graph.integrations import register_media_result
from ...project_graph.runtime import project_graph_service
from ..event_bus import event_bus
from ...runtime.resources import resource_keys_for_device
from ..tasks import TaskRecord, run_task, task_registry

router = APIRouter(prefix="/api/audio", tags=["audio-separation"])

_CACHE_TTL_SECONDS = 60.0
_cache_lock = threading.Lock()
_models_cache: tuple[float, tuple[Any, ...]] | None = None
_catalog_cache: tuple[float, tuple[Any, ...]] | None = None
_runtime_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_runtime_probes: set[tuple[str, str]] = set()

_METHOD_CONTROLS = {
    "mdx": {
        "segment_label": "Segment size",
        "segment_values": ["Default", "32", "64", "128", "256", "512"],
        "segment_default": "256",
        "overlap_label": "Overlap",
        "overlap_values": ["Default", "0.10", "0.25", "0.50", "0.75"],
        "overlap_default": "Default",
    },
    "mdxc": {
        "segment_label": "Segment size",
        "segment_values": ["Default", "32", "64", "128", "256", "512"],
        "segment_default": "256",
        "overlap_label": "Overlap",
        "overlap_values": ["Default", "2", "4", "8", "16"],
        "overlap_default": "8",
    },
    "vr": {
        "segment_label": "Window size",
        "segment_values": ["320", "512", "1024"],
        "segment_default": "512",
        "overlap_label": "Aggression",
        "overlap_values": ["Default", "5", "10", "15", "20"],
        "overlap_default": "Default",
    },
    "demucs": {
        "segment_label": "Segment length",
        "segment_values": ["Default", "10", "20", "30", "40"],
        "segment_default": "Default",
        "overlap_label": "Overlap",
        "overlap_values": ["Default", "0.10", "0.25", "0.50"],
        "overlap_default": "Default",
    },
}


class PresetRequest(BaseModel):
    name: str
    settings: dict[str, str | bool]


class SeparateRequest(BaseModel):
    galaxy_project_id: str = ""
    input_path: str
    output_dir: str
    project_name: str = ""
    method: str = MDX_METHOD
    model_filename: str = "Kim_Vocal_2.onnx"
    output_format: str = "WAV"
    segment_size: str = "256"
    overlap: str = "Default"
    processing_device: str = "auto"
    gpu_conversion: bool = True
    vocals_only: bool = False
    instrumental_only: bool = False
    sample_mode: bool = False


class DownloadModelRequest(BaseModel):
    filename: str


def _settings_path(request: Request) -> Path:
    configured = getattr(request.app.state, "settings_path", None)
    return Path(configured) if configured is not None else default_config_path()


def _presets_path(request: Request) -> Path:
    return _settings_path(request).with_name("audio_presets.json")


def _builtin_presets() -> dict[str, dict[str, str | bool]]:
    return {
        "Default": {
            "method": "mdx",
            "model_filename": "Kim_Vocal_2.onnx",
            "output_format": "WAV",
            "segment_size": "256",
            "overlap": "Default",
            "processing_device": "auto",
            "gpu_conversion": True,
            "vocals_only": False,
            "instrumental_only": False,
            "sample_mode": False,
        },
        "Vocal extraction": {
            "method": "mdx",
            "model_filename": "Kim_Vocal_2.onnx",
            "output_format": "WAV",
            "segment_size": "256",
            "overlap": "Default",
            "processing_device": "auto",
            "gpu_conversion": True,
            "vocals_only": True,
            "instrumental_only": False,
            "sample_mode": False,
        },
        "Instrumental / Karaoke": {
            "method": "mdx",
            "model_filename": "UVR-MDX-NET-Inst_HQ_5.onnx",
            "output_format": "WAV",
            "segment_size": "256",
            "overlap": "Default",
            "processing_device": "auto",
            "gpu_conversion": True,
            "vocals_only": False,
            "instrumental_only": True,
            "sample_mode": False,
        },
        "Denoise": {
            "method": "vr",
            "model_filename": "UVR-DeNoise-Lite.pth",
            "output_format": "WAV",
            "segment_size": "512",
            "overlap": "Default",
            "processing_device": "auto",
            "gpu_conversion": True,
            "vocals_only": False,
            "instrumental_only": False,
            "sample_mode": False,
        },
    }


def _cached_models(*, force: bool = False) -> tuple[Any, ...]:
    global _models_cache
    now = time.monotonic()
    with _cache_lock:
        if not force and _models_cache is not None and now - _models_cache[0] < _CACHE_TTL_SECONDS:
            return _models_cache[1]
    models = discover_uvr_models()
    with _cache_lock:
        _models_cache = (now, models)
    return models


def _cached_catalog(*, force: bool = False) -> tuple[Any, ...]:
    global _catalog_cache
    now = time.monotonic()
    with _cache_lock:
        if not force and _catalog_cache is not None and now - _catalog_cache[0] < 600:
            return _catalog_cache[1]
    models = list_downloadable_audio_models()
    with _cache_lock:
        _catalog_cache = (now, models)
    return models


def _invalidate_models_cache() -> None:
    global _models_cache
    with _cache_lock:
        _models_cache = None


def _run_runtime_probe(key: tuple[str, str]) -> None:
    device, method = key
    try:
        resolved = resolve_audio_device(device, method)
        ready, message = audio_separator_runtime_ready(
            default_audio_separator_runtime(), resolved, method
        )
        payload = {
            "state": "ready" if ready else "unavailable",
            "ready": ready,
            "message": message,
            "resolved_device": resolved,
        }
    except Exception as error:
        payload = {
            "state": "unavailable",
            "ready": False,
            "message": str(error),
            "resolved_device": None,
        }
    with _cache_lock:
        _runtime_cache[key] = (time.monotonic(), payload)
        _runtime_probes.discard(key)
    event_bus.emit({"type": "event", "kind": "audio_runtime_checked", "payload": payload})


def _runtime_status(device: str, method: str, *, force: bool = False) -> dict[str, Any]:
    key = (normalize_audio_device(device), normalize_audio_method(method))
    now = time.monotonic()
    with _cache_lock:
        cached = _runtime_cache.get(key)
        if not force and cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        if key not in _runtime_probes:
            _runtime_probes.add(key)
            threading.Thread(
                target=_run_runtime_probe,
                args=(key,),
                name=f"audio-runtime-{key[0]}-{key[1]}",
                daemon=True,
            ).start()
    return {
        "state": "checking",
        "ready": False,
        "message": "Đang kiểm tra runtime ở nền...",
        "resolved_device": None,
    }


def _progress(record: TaskRecord):
    def report(message: str) -> None:
        event_bus.emit({"type": "progress", "task_id": record.task_id, "message": message})

    return report


@router.get("/meta")
def get_meta() -> dict[str, Any]:
    runtime = default_audio_separator_runtime()
    uvr_root = default_uvr_root()
    installer = studio_root() / "install_audio_separator.ps1"
    return {
        "methods": [
            {"code": code, "label": AUDIO_PROCESS_METHOD_LABELS[code]}
            for code in AUDIO_PROCESS_METHODS
        ],
        "devices": [
            {"code": code, "label": AUDIO_PROCESSING_DEVICE_LABELS[code]}
            for code in AUDIO_PROCESSING_DEVICES
        ],
        "formats": list(AUDIO_OUTPUT_FORMATS),
        "method_controls": _METHOD_CONTROLS,
        "builtin_presets": _builtin_presets(),
        "uvr_root": str(uvr_root),
        "managed_models_root": str(default_managed_audio_models_root()),
        "runtime_path": str(runtime.python_path),
        "installer_available": installer.is_file(),
    }


@router.get("/models")
def get_models(refresh: bool = False) -> list[dict[str, Any]]:
    return [
        {
            "method": model.method,
            "label": model.label,
            "filename": model.filename,
        }
        for model in _cached_models(force=refresh)
    ]


@router.get("/models/catalog")
def get_model_catalog(refresh: bool = False) -> list[dict[str, object]]:
    try:
        catalog = _cached_catalog(force=refresh)
        return serialize_downloadable_audio_models(catalog, discover_uvr_models())
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/models/download")
def start_model_download(body: DownloadModelRequest) -> dict[str, str]:
    filename = body.filename.strip()
    if not filename or Path(filename).name != filename:
        raise HTTPException(status_code=422, detail="Tên model không hợp lệ.")
    try:
        model = next(
            (candidate for candidate in _cached_catalog() if candidate.filename == filename),
            None,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if model is None:
        raise HTTPException(status_code=404, detail="Model không còn trong catalog audio-separator.")

    record = task_registry.create("audio-model-download")
    record.on_cancel = lambda: managed_media_processes.terminate_task(record.task_id)

    def run_download() -> Path:
        path = download_audio_model(
            model,
            progress=_progress(record),
            stop_event=record.stop_event,
            task_id=record.task_id,
        )
        _invalidate_models_cache()
        return path

    run_task(record, run_download, lambda path: {"path": str(path), "filename": filename})
    return {"task_id": record.task_id}


@router.get("/runtime")
def get_runtime(device: str = "auto", method: str = "mdx", refresh: bool = False) -> dict[str, Any]:
    return _runtime_status(device, method, force=refresh)


@router.get("/presets")
def get_presets(request: Request) -> dict[str, Any]:
    return {
        "builtin": _builtin_presets(),
        "custom": load_audio_presets(_presets_path(request)),
    }


@router.post("/presets")
def save_preset(body: PresetRequest, request: Request) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tên preset không được để trống.")
    if name in AUDIO_SAVED_SETTINGS:
        raise HTTPException(status_code=409, detail="Tên preset này được dành cho cấu hình mặc định.")
    cleaned = {key: value for key, value in body.settings.items() if key in AUDIO_PRESET_FIELDS}
    if not cleaned:
        raise HTTPException(status_code=422, detail="Preset không có thiết lập hợp lệ.")
    path = _presets_path(request)
    presets = load_audio_presets(path)
    presets[name] = cleaned
    try:
        save_audio_presets(path, presets)
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Không lưu được preset: {error}") from error
    return {"name": name, "settings": load_audio_presets(path)[name]}


@router.delete("/presets/{name}")
def delete_preset(name: str, request: Request) -> dict[str, bool]:
    path = _presets_path(request)
    presets = load_audio_presets(path)
    if name not in presets:
        raise HTTPException(status_code=404, detail="Không tìm thấy preset tùy chỉnh.")
    del presets[name]
    try:
        save_audio_presets(path, presets)
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Không xóa được preset: {error}") from error
    return {"ok": True}


@router.post("/install")
def install_runtime(body: dict[str, Any]) -> dict[str, bool]:
    installer = studio_root() / "install_audio_separator.ps1"
    if not installer.is_file():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy bộ cài: {installer}")
    device = normalize_audio_device(str(body.get("device") or "auto"))
    command = [
        "powershell",
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(installer),
        "-Device",
        device,
    ]
    try:
        subprocess.Popen(
            command,
            cwd=installer.parent,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Không mở được bộ cài: {error}") from error
    return {"ok": True}


@router.post("/separate")
def start_separation(body: SeparateRequest, request: Request) -> dict[str, str]:
    input_path = Path(body.input_path).expanduser()
    if not input_path.is_file():
        raise HTTPException(status_code=422, detail="File audio/video đầu vào không tồn tại.")
    if not body.output_dir.strip():
        raise HTTPException(status_code=422, detail="Chọn thư mục xuất trước khi xử lý.")
    if body.vocals_only and body.instrumental_only:
        raise HTTPException(status_code=422, detail="Chỉ được chọn một loại stem duy nhất.")

    processing_device = body.processing_device if body.gpu_conversion else CPU_AUDIO_DEVICE
    options = AudioSeparationOptions(
        input_path=input_path,
        output_dir=Path(body.output_dir).expanduser(),
        project_name=body.project_name,
        method=body.method,
        model_filename=body.model_filename,
        output_format=body.output_format,
        segment_size=body.segment_size,
        overlap=body.overlap,
        processing_device=processing_device,
        vocals_only=body.vocals_only,
        instrumental_only=body.instrumental_only,
        sample_mode=body.sample_mode,
    )
    record = task_registry.create(
        "audio-separation",
        capability_id="audio.separation",
        resource_keys=resource_keys_for_device(processing_device),
    )
    record.on_cancel = lambda: managed_media_processes.terminate_task(record.task_id)
    graph_service = project_graph_service(_settings_path(request))

    def run_separation():
        from ...audio_separation.service import separate_audio

        return separate_audio(
            options,
            progress=_progress(record),
            stop_event=record.stop_event,
            task_id=record.task_id,
        )

    def serialize(result: Any) -> dict[str, Any]:
        register_media_result(
            graph_service,
            project_id=body.galaxy_project_id,
            workspace="separation",
            owner_id=record.task_id,
            label=body.project_name or input_path.stem,
            sources=(("source_media", str(input_path)),),
            outputs=tuple(
                [(f"audio_stem_{index + 1}", str(path)) for index, path in enumerate(result.output_paths)]
                + [("manifest", str(result.manifest_path))]
            ),
            metadata={"method": body.method, "model": body.model_filename},
        )
        return {
            "project_dir": str(result.project_dir),
            "output_paths": [str(path) for path in result.output_paths],
            "files": [
                {"name": path.name, "url": f"/api/files/task/{record.task_id}/{path.name}"}
                for path in result.output_paths
            ],
            "manifest_path": str(result.manifest_path),
            "warnings": list(result.warnings),
        }

    run_task(record, run_separation, serialize)
    return {"task_id": record.task_id}


def reset_audio_api_caches() -> None:
    """Clear process-local caches for tests and explicit refresh workflows."""
    global _catalog_cache, _models_cache
    with _cache_lock:
        _models_cache = None
        _catalog_cache = None
        _runtime_cache.clear()
        _runtime_probes.clear()
