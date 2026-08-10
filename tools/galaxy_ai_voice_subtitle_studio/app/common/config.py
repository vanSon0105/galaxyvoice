from __future__ import annotations

import json
import math
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..audio_separation.service import (
    AUDIO_OUTPUT_FORMATS,
    AUTO_AUDIO_DEVICE,
    MDX_METHOD,
    normalize_audio_device,
    normalize_audio_method,
)
from .compute import AUTO_DEVICE, normalize_processing_device
from .paths import studio_root
from ..subtitle_removal.service import BLUR_MODE, SUBTITLE_REMOVAL_MODES
from ..voice.transcription import WHISPER_MODELS
from ..voice.translator import translation_provider_codes
from ..voice.tts import tts_engine_codes
from ..video_editor.service import (
    EDITOR_AUDIO_MODES,
    EDITOR_ENCODERS,
    EDITOR_FPS_OPTIONS,
    EDITOR_RESOLUTIONS,
    AUTO_ENCODER,
    MIX_AUDIO,
    ORIGINAL_RESOLUTION,
    SOURCE_FPS,
)


CONFIG_VERSION = 4


@dataclass(frozen=True)
class AppConfig:
    version: int = CONFIG_VERSION
    output_dir: str = ""
    tts_engine: str = "edge"
    voice_name: str = ""
    rate: int = 0
    volume: int = 100
    pause_ms: int = 250
    max_chars: int = 160
    export_mp3: bool = True
    keep_segments: bool = True
    video_export_wav: bool = True
    video_export_mp3: bool = True
    video_source_language: str = "auto"
    video_target_language: str = "vi"
    whisper_model: str = "base"
    voice_processing_device: str = AUTO_DEVICE
    ai_provider: str = ""
    ai_model: str = ""
    ai_base_url: str = ""
    subtitle_removal_mode: str = BLUR_MODE
    subtitle_region_x: int = 5
    subtitle_region_y: int = 75
    subtitle_region_width: int = 90
    subtitle_region_height: int = 20
    subtitle_blur_strength: int = 18
    removal_processing_device: str = AUTO_DEVICE
    propainter_license_accepted: bool = False
    audio_output_dir: str = ""
    audio_process_method: str = MDX_METHOD
    audio_model_name: str = "Kim_Vocal_2.onnx"
    audio_output_format: str = "WAV"
    audio_segment_size: str = "256"
    audio_overlap: str = "Default"
    audio_processing_device: str = AUTO_AUDIO_DEVICE
    audio_gpu_conversion: bool = True
    audio_vocals_only: bool = False
    audio_instrumental_only: bool = False
    audio_sample_mode: bool = False
    audio_saved_setting: str = "Default"
    editor_output_dir: str = ""
    editor_resolution: str = ORIGINAL_RESOLUTION
    editor_fps: str = SOURCE_FPS
    editor_encoder: str = AUTO_ENCODER
    editor_audio_mode: str = MIX_AUDIO
    editor_source_volume: int = 100
    editor_external_volume: int = 100
    editor_subtitle_font_size: int = 22
    editor_subtitle_margin: int = 36
    editor_timeline_zoom: float = 80.0


def default_config_path() -> Path:
    return studio_root() / "config.json"


def load_app_config(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AppConfig()
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        _preserve_invalid_config(config_path)
        return AppConfig()
    if not isinstance(payload, dict):
        _preserve_invalid_config(config_path)
        return AppConfig()

    defaults = AppConfig()
    engine = _string(payload.get("tts_engine"), defaults.tts_engine).lower()
    if engine not in tts_engine_codes():
        engine = defaults.tts_engine

    whisper_model = _string(payload.get("whisper_model"), defaults.whisper_model)
    if whisper_model not in WHISPER_MODELS:
        whisper_model = defaults.whisper_model

    provider = _string(payload.get("ai_provider"), defaults.ai_provider).lower()
    if provider and provider not in translation_provider_codes():
        provider = defaults.ai_provider

    removal_mode = _string(
        payload.get("subtitle_removal_mode"), defaults.subtitle_removal_mode
    ).lower()
    if removal_mode not in SUBTITLE_REMOVAL_MODES:
        removal_mode = defaults.subtitle_removal_mode

    audio_output_format = _string(
        payload.get("audio_output_format"), defaults.audio_output_format
    ).upper()
    if audio_output_format not in AUDIO_OUTPUT_FORMATS:
        audio_output_format = defaults.audio_output_format
    audio_saved_setting = _string(
        payload.get("audio_saved_setting"), defaults.audio_saved_setting
    ) or defaults.audio_saved_setting
    editor_resolution = _choice(
        payload.get("editor_resolution"), defaults.editor_resolution, set(EDITOR_RESOLUTIONS)
    )
    editor_fps = _choice(payload.get("editor_fps"), defaults.editor_fps, set(EDITOR_FPS_OPTIONS))
    editor_encoder = _choice(
        payload.get("editor_encoder"), defaults.editor_encoder, set(EDITOR_ENCODERS)
    )
    editor_audio_mode = _choice(
        payload.get("editor_audio_mode"), defaults.editor_audio_mode, set(EDITOR_AUDIO_MODES)
    )

    subtitle_region_x = _integer(
        payload.get("subtitle_region_x"), defaults.subtitle_region_x, 0, 99
    )
    subtitle_region_y = _integer(
        payload.get("subtitle_region_y"), defaults.subtitle_region_y, 0, 99
    )
    subtitle_region_width = min(
        _integer(payload.get("subtitle_region_width"), defaults.subtitle_region_width, 1, 100),
        100 - subtitle_region_x,
    )
    subtitle_region_height = min(
        _integer(payload.get("subtitle_region_height"), defaults.subtitle_region_height, 1, 100),
        100 - subtitle_region_y,
    )

    return AppConfig(
        output_dir=_string(payload.get("output_dir"), defaults.output_dir),
        tts_engine=engine,
        voice_name=_string(payload.get("voice_name"), defaults.voice_name),
        rate=_integer(payload.get("rate"), defaults.rate, -10, 10),
        volume=_integer(payload.get("volume"), defaults.volume, 0, 100),
        pause_ms=_integer(payload.get("pause_ms"), defaults.pause_ms, 0, 1200),
        max_chars=_integer(payload.get("max_chars"), defaults.max_chars, 60, 260),
        export_mp3=_boolean(payload.get("export_mp3"), defaults.export_mp3),
        keep_segments=_boolean(payload.get("keep_segments"), defaults.keep_segments),
        video_export_wav=_boolean(payload.get("video_export_wav"), defaults.video_export_wav),
        video_export_mp3=_boolean(payload.get("video_export_mp3"), defaults.video_export_mp3),
        video_source_language=_string(
            payload.get("video_source_language"), defaults.video_source_language
        ).lower(),
        video_target_language=_string(
            payload.get("video_target_language"), defaults.video_target_language
        ).lower(),
        whisper_model=whisper_model,
        voice_processing_device=normalize_processing_device(
            _string(payload.get("voice_processing_device"), defaults.voice_processing_device)
        ),
        ai_provider=provider,
        ai_model=_string(payload.get("ai_model"), defaults.ai_model),
        ai_base_url=_string(payload.get("ai_base_url"), defaults.ai_base_url),
        subtitle_removal_mode=removal_mode,
        subtitle_region_x=subtitle_region_x,
        subtitle_region_y=subtitle_region_y,
        subtitle_region_width=subtitle_region_width,
        subtitle_region_height=subtitle_region_height,
        subtitle_blur_strength=_integer(
            payload.get("subtitle_blur_strength"), defaults.subtitle_blur_strength, 1, 100
        ),
        removal_processing_device=normalize_processing_device(
            _string(payload.get("removal_processing_device"), defaults.removal_processing_device)
        ),
        propainter_license_accepted=_boolean(
            payload.get("propainter_license_accepted"), defaults.propainter_license_accepted
        ),
        audio_output_dir=_string(payload.get("audio_output_dir"), defaults.audio_output_dir),
        audio_process_method=normalize_audio_method(
            _string(payload.get("audio_process_method"), defaults.audio_process_method)
        ),
        audio_model_name=_string(payload.get("audio_model_name"), defaults.audio_model_name),
        audio_output_format=audio_output_format,
        audio_segment_size=_string(
            payload.get("audio_segment_size"), defaults.audio_segment_size
        ),
        audio_overlap=_string(payload.get("audio_overlap"), defaults.audio_overlap),
        audio_processing_device=normalize_audio_device(
            _string(payload.get("audio_processing_device"), defaults.audio_processing_device)
        ),
        audio_gpu_conversion=_boolean(
            payload.get("audio_gpu_conversion"), defaults.audio_gpu_conversion
        ),
        audio_vocals_only=_boolean(
            payload.get("audio_vocals_only"), defaults.audio_vocals_only
        ),
        audio_instrumental_only=_boolean(
            payload.get("audio_instrumental_only"), defaults.audio_instrumental_only
        ),
        audio_sample_mode=_boolean(
            payload.get("audio_sample_mode"), defaults.audio_sample_mode
        ),
        audio_saved_setting=audio_saved_setting,
        editor_output_dir=_string(payload.get("editor_output_dir"), defaults.editor_output_dir),
        editor_resolution=editor_resolution,
        editor_fps=editor_fps,
        editor_encoder=editor_encoder,
        editor_audio_mode=editor_audio_mode,
        editor_source_volume=_integer(
            payload.get("editor_source_volume"), defaults.editor_source_volume, 0, 200
        ),
        editor_external_volume=_integer(
            payload.get("editor_external_volume"), defaults.editor_external_volume, 0, 200
        ),
        editor_subtitle_font_size=_integer(
            payload.get("editor_subtitle_font_size"), defaults.editor_subtitle_font_size, 10, 72
        ),
        editor_subtitle_margin=_integer(
            payload.get("editor_subtitle_margin"), defaults.editor_subtitle_margin, 0, 300
        ),
        editor_timeline_zoom=_number(
            payload.get("editor_timeline_zoom"), defaults.editor_timeline_zoom, 0.1, 300.0
        ),
    )


def save_app_config(config: AppConfig, path: Path | None = None) -> None:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(asdict(config), temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
        os.replace(temp_path, config_path)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _preserve_invalid_config(config_path: Path) -> None:
    backup_path = config_path.with_name(
        f"{config_path.name}.invalid-{uuid.uuid4().hex}"
    )
    try:
        config_path.replace(backup_path)
    except OSError:
        pass


def _string(value: Any, default: str) -> str:
    return value.strip() if isinstance(value, str) else default


def _integer(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(minimum, min(maximum, value))


def _number(value: Any, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    if not math.isfinite(number):
        return default
    return max(minimum, min(maximum, number))


def _boolean(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _choice(value: Any, default: str, choices: set[str]) -> str:
    normalized = _string(value, default).lower()
    return normalized if normalized in choices else default
