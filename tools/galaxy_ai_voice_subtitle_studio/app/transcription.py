from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .ffmpeg import ffmpeg_missing_message, find_ffmpeg
from .media import Runner, _run_command, _run_ffmpeg, build_extract_wav_command
from .paths import unique_project_dir
from .srt import SubtitleCue, parse_srt, render_srt
from .translator import (
    AITranslationOptions,
    default_translation_api_key,
    default_translation_base_url,
    default_translation_model,
    default_translation_provider,
    normalize_translation_provider,
    translate_cues,
    validate_translation_options,
)

WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")

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
    ai_provider: str = ""
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
    script_text: str
    script_language: str
    warnings: list[str]


@dataclass(frozen=True)
class VideoSubtitleDraft:
    source_video: Path
    project_name: str
    audio_path: Path
    source_language: str
    target_language: str
    whisper_model: str
    ai_provider: str
    ai_model: str
    ai_base_url: str
    source_cues: tuple[SubtitleCue, ...]
    translated_cues: tuple[SubtitleCue, ...] | None
    warnings: list[str]
    _workspace: tempfile.TemporaryDirectory[str] | None = field(default=None, repr=False, compare=False)

    @property
    def cue_count(self) -> int:
        return len(self.source_cues)

    @property
    def source_srt_text(self) -> str:
        return render_srt(list(self.source_cues))

    @property
    def translated_srt_text(self) -> str:
        return render_srt(list(self.translated_cues or ()))

    @property
    def script_text(self) -> str:
        return cues_to_script(list(self.translated_cues or self.source_cues))

    @property
    def script_language(self) -> str:
        return self.target_language if self.translated_cues is not None else self.source_language

    def cleanup(self) -> None:
        if self._workspace is not None:
            self._workspace.cleanup()


def create_subtitles_from_video(
    options: VideoSubtitleOptions,
    progress: ProgressCallback | None = None,
    ffmpeg_path: str | None = None,
    runner: Runner | None = None,
    transcriber: Transcriber | None = None,
    translator: CueTranslator | None = None,
) -> VideoSubtitleResult:
    draft = prepare_subtitles_from_video(
        options,
        progress=progress,
        ffmpeg_path=ffmpeg_path,
        runner=runner,
        transcriber=transcriber,
        translator=translator,
    )
    try:
        return export_subtitle_package(
            draft,
            options.output_dir,
            options.project_name,
            progress=progress,
        )
    finally:
        draft.cleanup()


def prepare_subtitles_from_video(
    options: VideoSubtitleOptions,
    progress: ProgressCallback | None = None,
    ffmpeg_path: str | None = None,
    runner: Runner | None = None,
    transcriber: Transcriber | None = None,
    translator: CueTranslator | None = None,
) -> VideoSubtitleDraft:
    report = progress or (lambda _message: None)
    video_path = Path(options.video_path).expanduser()
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    ffmpeg = ffmpeg_path or find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(ffmpeg_missing_message("create subtitles from video"))

    source_language = _normalize_language(options.source_language, auto_value="auto")
    target_language = _normalize_language(options.target_language, auto_value="none")
    ai_provider = normalize_translation_provider(options.ai_provider or default_translation_provider())
    ai_options = AITranslationOptions(
        source_language=source_language,
        target_language=target_language,
        provider=ai_provider,
        api_key=options.ai_api_key or default_translation_api_key(ai_provider),
        model=options.ai_model or default_translation_model(ai_provider),
        base_url=options.ai_base_url or default_translation_base_url(ai_provider),
    )
    if target_language != "none":
        validate_translation_options(ai_options)

    run = runner or _run_command
    transcribe = transcriber or transcribe_with_faster_whisper
    translate = translator or translate_cues
    warnings: list[str] = []
    workspace = tempfile.TemporaryDirectory(prefix="galaxy_subtitles_")
    audio_path = Path(workspace.name) / "speech.wav"

    try:
        report("Extracting speech audio...")
        _run_ffmpeg(build_extract_wav_command(ffmpeg, video_path, audio_path), run)

        report("Transcribing speech...")
        whisper_language = None if source_language == "auto" else source_language
        cues = transcribe(audio_path, whisper_language, options.whisper_model, report)
        if not cues:
            raise RuntimeError("No speech segments were detected in the video.")

        translated_cues: list[SubtitleCue] | None = None
        if target_language != "none":
            report("Translating subtitles with AI...")
            translated_cues = translate(cues, ai_options)

        report("Subtitles are ready for review.")
        return VideoSubtitleDraft(
            source_video=video_path,
            project_name=options.project_name or video_path.stem,
            audio_path=audio_path,
            source_language=source_language,
            target_language=target_language,
            whisper_model=options.whisper_model,
            ai_provider=ai_options.provider,
            ai_model=ai_options.model,
            ai_base_url=ai_options.base_url,
            source_cues=tuple(cues),
            translated_cues=tuple(translated_cues) if translated_cues is not None else None,
            warnings=warnings,
            _workspace=workspace,
        )
    except Exception:
        workspace.cleanup()
        raise


def export_subtitle_package(
    draft: VideoSubtitleDraft,
    output_dir: Path,
    project_name: str | None = None,
    source_srt_text: str | None = None,
    translated_srt_text: str | None = None,
    progress: ProgressCallback | None = None,
) -> VideoSubtitleResult:
    report = progress or (lambda _message: None)
    if not draft.audio_path.exists():
        raise FileNotFoundError("Subtitle working audio is no longer available. Create subtitles again.")

    source_text = _export_srt_text(source_srt_text if source_srt_text is not None else draft.source_srt_text)
    source_cues = parse_srt(source_text)
    translated_text = None
    translated_cues: list[SubtitleCue] | None = None
    if draft.translated_cues is not None:
        translated_text = _export_srt_text(
            translated_srt_text if translated_srt_text is not None else draft.translated_srt_text
        )
        translated_cues = parse_srt(translated_text)
        if len(translated_cues) != len(source_cues):
            raise ValueError("Original and translated SRT must contain the same number of cues.")

    export_name = project_name if project_name is not None else draft.project_name
    project_dir = unique_project_dir(output_dir, export_name or draft.source_video.stem, fallback_prefix="subtitles")
    project_slug = project_dir.name
    audio_path = project_dir / f"{project_slug}_speech.wav"
    source_srt_path = project_dir / f"{project_slug}_original.srt"
    translated_srt_path = (
        project_dir / f"{project_slug}_{draft.target_language}.srt"
        if translated_text is not None
        else None
    )
    manifest_path = project_dir / "subtitle_manifest.json"

    script_cues = translated_cues if translated_cues is not None else source_cues
    script_text = cues_to_script(script_cues)
    script_language = draft.target_language if translated_cues is not None else draft.source_language

    try:
        report("Exporting subtitle package...")
        shutil.copy2(draft.audio_path, audio_path)
        source_srt_path.write_text(source_text, encoding="utf-8")
        if translated_srt_path is not None and translated_text is not None:
            translated_srt_path.write_text(translated_text, encoding="utf-8")

        manifest = {
            "app": "Galaxy AI Voice & Subtitle Studio",
            "version": "0.1.0",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_video": str(draft.source_video),
            "source_language": draft.source_language,
            "target_language": draft.target_language,
            "whisper_model": draft.whisper_model,
            "ai_provider": draft.ai_provider if translated_srt_path else None,
            "ai_model": draft.ai_model if translated_srt_path else None,
            "ai_base_url": draft.ai_base_url if translated_srt_path else None,
            "cue_count": len(source_cues),
            "files": {
                "audio": audio_path.name,
                "source_srt": source_srt_path.name,
                "translated_srt": translated_srt_path.name if translated_srt_path else None,
            },
            "warnings": draft.warnings,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        report("Done.")
    except Exception as export_error:
        try:
            shutil.rmtree(project_dir)
        except Exception as cleanup_error:
            raise RuntimeError(
                f"Subtitle export failed ({export_error}) and the incomplete folder could not be removed "
                f"({cleanup_error}): {project_dir}"
            ) from export_error
        raise

    return VideoSubtitleResult(
        project_dir=project_dir,
        audio_path=audio_path,
        source_srt_path=source_srt_path,
        translated_srt_path=translated_srt_path,
        manifest_path=manifest_path,
        cue_count=len(source_cues),
        script_text=script_text,
        script_language=script_language,
        warnings=list(draft.warnings),
    )


def _export_srt_text(text: str) -> str:
    if not text.strip():
        raise ValueError("Subtitle content is empty.")
    return text.rstrip("\r\n") + "\n"


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


def cues_to_script(cues: list[SubtitleCue]) -> str:
    return "\n".join(cue.text.strip() for cue in cues if cue.text.strip())
