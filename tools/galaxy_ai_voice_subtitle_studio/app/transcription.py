from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .ffmpeg import ffmpeg_missing_message, find_ffmpeg
from .media import Runner, _run_command, _run_ffmpeg, build_extract_wav_command
from .paths import unique_project_dir
from .srt import SubtitleCue, render_srt
from .translator import (
    AITranslationOptions,
    default_translation_api_key,
    default_translation_base_url,
    default_translation_model,
    translate_cues,
    validate_translation_options,
)

ProgressCallback = Callable[[str], None]
Transcriber = Callable[[Path, str | None, str, ProgressCallback], list[SubtitleCue]]
CueTranslator = Callable[[list[SubtitleCue], AITranslationOptions], list[SubtitleCue]]


@dataclass(frozen=True)
class VideoSubtitleOptions:
    video_path: Path
    output_dir: Path
    project_name: str = ""
    source_language: str = "auto"
    target_language: str = "vi"
    whisper_model: str = "base"
    ai_model: str = ""
    ai_base_url: str = ""
    ai_api_key: str = ""


@dataclass(frozen=True)
class VideoSubtitleResult:
    project_dir: Path
    audio_path: Path
    source_srt_path: Path
    translated_srt_path: Path | None
    manifest_path: Path
    cue_count: int
    warnings: list[str]


def create_subtitles_from_video(
    options: VideoSubtitleOptions,
    progress: ProgressCallback | None = None,
    ffmpeg_path: str | None = None,
    runner: Runner | None = None,
    transcriber: Transcriber | None = None,
    translator: CueTranslator | None = None,
) -> VideoSubtitleResult:
    report = progress or (lambda _message: None)
    video_path = Path(options.video_path).expanduser()
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    ffmpeg = ffmpeg_path or find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(ffmpeg_missing_message("create subtitles from video"))

    source_language = _normalize_language(options.source_language, auto_value="auto")
    target_language = _normalize_language(options.target_language, auto_value="none")
    ai_options = AITranslationOptions(
        source_language=source_language,
        target_language=target_language,
        api_key=options.ai_api_key or default_translation_api_key(),
        model=options.ai_model or default_translation_model(),
        base_url=options.ai_base_url or default_translation_base_url(),
    )
    if target_language != "none":
        validate_translation_options(ai_options)

    project_name = options.project_name or video_path.stem
    project_dir = unique_project_dir(options.output_dir, project_name, fallback_prefix="subtitles")
    project_slug = project_dir.name
    audio_path = project_dir / f"{project_slug}_speech.wav"
    source_srt_path = project_dir / f"{project_slug}_original.srt"
    translated_srt_path = project_dir / f"{project_slug}_{target_language}.srt" if target_language != "none" else None
    manifest_path = project_dir / "subtitle_manifest.json"
    run = runner or _run_command
    transcribe = transcriber or transcribe_with_faster_whisper
    translate = translator or translate_cues
    warnings: list[str] = []

    report("Extracting speech audio...")
    _run_ffmpeg(build_extract_wav_command(ffmpeg, video_path, audio_path), run)

    report("Transcribing speech...")
    whisper_language = None if source_language == "auto" else source_language
    cues = transcribe(audio_path, whisper_language, options.whisper_model, report)
    if not cues:
        raise RuntimeError("No speech segments were detected in the video.")

    source_srt_path.write_text(render_srt(cues), encoding="utf-8")

    translated_cues: list[SubtitleCue] | None = None
    if translated_srt_path:
        report("Translating subtitles with AI...")
        translated_cues = translate(cues, ai_options)
        translated_srt_path.write_text(render_srt(translated_cues), encoding="utf-8")

    manifest = {
        "app": "Galaxy AI Voice & Subtitle Studio",
        "version": "0.1.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_video": str(video_path),
        "source_language": source_language,
        "target_language": target_language,
        "whisper_model": options.whisper_model,
        "ai_model": ai_options.model if translated_srt_path else None,
        "ai_base_url": ai_options.base_url if translated_srt_path else None,
        "cue_count": len(cues),
        "files": {
            "audio": audio_path.name,
            "source_srt": source_srt_path.name,
            "translated_srt": translated_srt_path.name if translated_srt_path else None,
        },
        "warnings": warnings,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report("Done.")

    return VideoSubtitleResult(
        project_dir=project_dir,
        audio_path=audio_path,
        source_srt_path=source_srt_path,
        translated_srt_path=translated_srt_path,
        manifest_path=manifest_path,
        cue_count=len(cues),
        warnings=warnings,
    )


def transcribe_with_faster_whisper(
    audio_path: Path,
    source_language: str | None,
    model_size: str,
    progress: ProgressCallback,
) -> list[SubtitleCue]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install -r requirements-transcription.txt"
        ) from error

    progress(f"Loading Whisper model: {model_size}")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(audio_path),
        language=source_language,
        vad_filter=True,
        beam_size=5,
    )

    cues: list[SubtitleCue] = []
    for index, segment in enumerate(segments, start=1):
        text = str(segment.text).strip()
        if not text:
            continue
        cues.append(
            SubtitleCue(
                index=len(cues) + 1,
                start_ms=round(float(segment.start) * 1000),
                end_ms=round(float(segment.end) * 1000),
                text=text,
            )
        )
        if index % 10 == 0:
            progress(f"Transcribed {index} segments...")

    return cues


def _normalize_language(value: str, auto_value: str) -> str:
    normalized = value.strip().lower()
    return normalized or auto_value
