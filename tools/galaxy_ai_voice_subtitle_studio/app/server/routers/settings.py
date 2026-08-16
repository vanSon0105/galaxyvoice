"""Settings & system endpoints: shared config.json CRUD plus UI metadata.

API keys never appear here: AppConfig deliberately has no secret fields,
and the translation API key flows through env vars / per-request input only.
"""
from __future__ import annotations

from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ...common.compute import PROCESSING_DEVICES, PROCESSING_DEVICE_LABELS
from ...common.config import (
    AppConfig,
    config_from_payload,
    default_config_path,
    load_app_config,
    save_app_config,
)
from ...common.processes import managed_media_processes
from ...audio_separation.service import (
    AUDIO_OUTPUT_FORMATS,
    AUDIO_PROCESS_METHODS,
    AUDIO_PROCESS_METHOD_LABELS,
    AUDIO_PROCESSING_DEVICES,
    AUDIO_PROCESSING_DEVICE_LABELS,
)
from ...omnivoice.runtime import OMNIVOICE_DEVICES, omnivoice_device_label
from ...subtitle_removal.constants import REMOVAL_MODE_LABELS
from ...video_editor.service import (
    AUDIO_MODE_LABELS,
    EDITOR_AUDIO_MODES,
    EDITOR_ENCODERS,
    EDITOR_FPS_OPTIONS,
    EDITOR_RESOLUTIONS,
    ENCODER_LABELS,
    FPS_LABELS,
    RESOLUTION_LABELS,
)
from ...voice.languages import LANGUAGE_CHOICES, TARGET_LANGUAGE_CHOICES
from ...voice.transcription import WHISPER_MODELS
from ...voice.translator import (
    default_translation_base_url,
    default_translation_model,
    default_translation_provider,
    translation_provider_codes,
    translation_provider_label,
)
from ...voice.tts import create_tts_engine, tts_engine_codes
from ..tasks import task_registry

router = APIRouter(prefix="/api")

_CONFIG_FIELDS = {field.name for field in fields(AppConfig)}


def _settings_path(request: Request) -> Path:
    path = getattr(request.app.state, "settings_path", None)
    return Path(path) if path is not None else default_config_path()


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    return asdict(load_app_config(_settings_path(request)))


@router.put("/settings")
def update_settings(body: dict[str, Any], request: Request) -> dict[str, Any]:
    path = _settings_path(request)
    current = load_app_config(path)
    merged = {
        **asdict(current),
        **{key: value for key, value in body.items() if key in _CONFIG_FIELDS},
    }
    validated = config_from_payload(merged)
    try:
        save_app_config(validated, path)
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Không lưu được config: {error}")
    return asdict(validated)


@router.get("/settings/meta")
def get_settings_meta() -> dict[str, Any]:
    engines = [
        {
            "code": code,
            "label": create_tts_engine(code).label,
        }
        for code in tts_engine_codes()
    ]
    provider_codes = translation_provider_codes()
    providers = [
        {
            "code": code,
            "label": translation_provider_label(code),
            "default_model": default_translation_model(code),
            "default_base_url": default_translation_base_url(code),
        }
        for code in provider_codes
    ]
    return {
        "tts_engines": engines,
        "default_tts_engine": tts_engine_codes()[0],
        "whisper_models": list(WHISPER_MODELS),
        "translation_providers": providers,
        "default_translation_provider": default_translation_provider(),
        "source_languages": [{"code": code, "label": label} for code, label in LANGUAGE_CHOICES],
        "target_languages": [
            {"code": code, "label": label} for code, label in TARGET_LANGUAGE_CHOICES
        ],
        "processing_devices": [
            {"code": code, "label": PROCESSING_DEVICE_LABELS[code]}
            for code in PROCESSING_DEVICES
        ],
        "audio_methods": [
            {"code": code, "label": AUDIO_PROCESS_METHOD_LABELS[code]}
            for code in AUDIO_PROCESS_METHODS
        ],
        "audio_devices": [
            {"code": code, "label": AUDIO_PROCESSING_DEVICE_LABELS[code]}
            for code in AUDIO_PROCESSING_DEVICES
        ],
        "audio_formats": list(AUDIO_OUTPUT_FORMATS),
        "removal_modes": [
            {"code": code, "label": label} for code, label in REMOVAL_MODE_LABELS.items()
        ],
        "editor_resolutions": [
            {"code": code, "label": RESOLUTION_LABELS.get(code, code)}
            for code in EDITOR_RESOLUTIONS
        ],
        "editor_fps": [
            {"code": code, "label": FPS_LABELS.get(code, code)} for code in EDITOR_FPS_OPTIONS
        ],
        "editor_encoders": [
            {"code": code, "label": ENCODER_LABELS.get(code, code)} for code in EDITOR_ENCODERS
        ],
        "editor_audio_modes": [
            {"code": code, "label": AUDIO_MODE_LABELS.get(code, code)}
            for code in EDITOR_AUDIO_MODES
        ],
        "omnivoice_devices": [
            {"code": code, "label": omnivoice_device_label(code)} for code in OMNIVOICE_DEVICES
        ],
    }


@router.get("/system/processes")
def get_system_processes() -> dict[str, Any]:
    return {
        "media_processes": managed_media_processes.snapshot(),
        "running_tasks": task_registry.running_count(),
    }
