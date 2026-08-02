from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .compute import AUTO_DEVICE, normalize_processing_device
from .subtitle_removal import BLUR_MODE, SUBTITLE_REMOVAL_MODES
from .transcription import WHISPER_MODELS
from .translator import translation_provider_codes
from .tts import tts_engine_codes


CONFIG_VERSION = 2


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


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config.json"


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


def _boolean(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default
