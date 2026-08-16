from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..common.cache import default_cache_dir, file_digest, read_json, stable_digest, write_json_atomic
from ..common.compute import AUTO_DEVICE, normalize_processing_device, resolve_whisper_runtime
from ..common.errors import TaskCancelledError
from ..common.ffmpeg import ffmpeg_missing_message, find_ffmpeg
from .media import Runner, _run_command, _run_ffmpeg, build_extract_wav_command
from ..common.paths import unique_project_dir
from .srt import SubtitleCue, parse_srt, render_srt
from .translator import (
    AITranslationOptions,
    default_translation_api_key,
    default_translation_base_url,
    default_translation_model,
    default_translation_provider,
    normalize_translation_provider,
    translation_checkpoint_path,
    translate_cues,
    validate_translation_options,
)

WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")
TRANSCRIPTION_CACHE_VERSION = 1

ProgressCallback = Callable[[str], None]
DetailedProgressCallback = Callable[[str, int, int], None]
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
    processing_device: str = AUTO_DEVICE
    ai_provider: str = ""
    ai_model: str = ""
    ai_base_url: str = ""
    ai_api_key: str = ""
    cache_dir: Path | None = None
    translation_batch_size: int = 2
    translation_workers: int = 6


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
    detailed_progress: DetailedProgressCallback | None = None,
    stop_event: threading.Event | None = None,
) -> VideoSubtitleResult:
    draft = prepare_subtitles_from_video(
        options,
        progress=progress,
        detailed_progress=detailed_progress,
        ffmpeg_path=ffmpeg_path,
        runner=runner,
        transcriber=transcriber,
        translator=translator,
        stop_event=stop_event,
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
    detailed_progress: DetailedProgressCallback | None = None,
    stop_event: threading.Event | None = None,
) -> VideoSubtitleDraft:
    report = progress or (lambda _message: None)
    report_detail = detailed_progress or (lambda _stage, _completed, _total: None)
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
        batch_size=options.translation_batch_size,
        max_workers=options.translation_workers,
    )
    if target_language != "none":
        validate_translation_options(ai_options)

    run = runner or _run_command
    transcribe = transcriber or transcribe_with_faster_whisper
    translate = translator or translate_cues
    warnings: list[str] = []
    cache_root: Path | None = None
    workspace = tempfile.TemporaryDirectory(prefix="galaxy_subtitles_")
    audio_path = Path(workspace.name) / "speech.wav"

    try:
        report("Extracting speech audio...")
        _run_ffmpeg(build_extract_wav_command(ffmpeg, video_path, audio_path), run, stop_event=stop_event)

        cache_enabled = options.cache_dir is not None or transcriber is None
        transcription_cache_path: Path | None = None
        cues: list[SubtitleCue] | None = None
        if cache_enabled:
            cache_root = Path(options.cache_dir) if options.cache_dir is not None else default_cache_dir()
            transcription_cache_path = _transcription_cache_path(
                cache_root,
                video_path,
                source_language,
                options.whisper_model,
            )
            cues = _load_transcription_cache(transcription_cache_path)
        if cues is not None:
            report(f"Loaded {len(cues)} cues from cached transcription.")
            report_detail("Transcribing", len(cues), len(cues))
        else:
            report("Transcribing speech...")
            whisper_language = None if source_language == "auto" else source_language
            if transcriber is None:
                cues = transcribe_with_faster_whisper(
                    audio_path,
                    whisper_language,
                    options.whisper_model,
                    report,
                    processing_device=options.processing_device,
                    stop_event=stop_event,
                )
            else:
                if stop_event is not None and stop_event.is_set():
                    raise TaskCancelledError()
                cues = transcribe(audio_path, whisper_language, options.whisper_model, report)
            if cues and transcription_cache_path is not None:
                try:
                    _save_transcription_cache(transcription_cache_path, cues)
                except OSError as error:
                    warnings.append(f"Could not save transcription cache: {error}")
        if not cues:
            raise RuntimeError("No speech segments were detected in the video.")

        translated_cues: list[SubtitleCue] | None = None
        if target_language != "none":
            if stop_event is not None and stop_event.is_set():
                raise TaskCancelledError()
            report("Translating subtitles with AI...")
            report_detail("Translating", 0, len(cues))
            if translator is None:
                checkpoint_path = (
                    translation_checkpoint_path(cache_root, cues, ai_options)
                    if cache_root is not None
                    else None
                )
                last_reported = -10

                def report_translation_progress(completed: int, total: int) -> None:
                    nonlocal last_reported
                    report_detail("Translating", completed, total)
                    if completed == total or completed == 0 or completed >= last_reported + 10:
                        report(f"Translated {completed}/{total} cues...")
                        last_reported = completed

                translated_cues = translate_cues(
                    cues,
                    ai_options,
                    progress=report_translation_progress,
                    checkpoint_path=checkpoint_path,
                    warning=warnings.append,
                )
            else:
                translated_cues = translate(cues, ai_options)
                report_detail("Translating", len(cues), len(cues))

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


def _transcription_cache_path(
    cache_dir: Path,
    video_path: Path,
    source_language: str,
    whisper_model: str,
) -> Path:
    stat = video_path.stat()
    digest = stable_digest(
        {
            "version": TRANSCRIPTION_CACHE_VERSION,
            "video_path": str(video_path.resolve()),
            "video_size": stat.st_size,
            "video_mtime_ns": stat.st_mtime_ns,
            "video_sha256": file_digest(video_path),
            "source_language": source_language,
            "whisper_model": whisper_model,
        }
    )
    return cache_dir / "transcriptions" / f"{digest}.json"


def _load_transcription_cache(path: Path) -> list[SubtitleCue] | None:
    payload = read_json(path)
    if not isinstance(payload, dict) or payload.get("version") != TRANSCRIPTION_CACHE_VERSION:
        return None
    raw_cues = payload.get("cues")
    if not isinstance(raw_cues, list) or not raw_cues:
        return None

    cues: list[SubtitleCue] = []
    try:
        for raw_cue in raw_cues:
            if not isinstance(raw_cue, dict):
                return None
            cue = SubtitleCue(
                index=int(raw_cue["index"]),
                start_ms=int(raw_cue["start_ms"]),
                end_ms=int(raw_cue["end_ms"]),
                text=str(raw_cue["text"]).strip(),
            )
            if cue.index < 1 or cue.start_ms < 0 or cue.end_ms <= cue.start_ms or not cue.text:
                return None
            cues.append(cue)
    except (KeyError, TypeError, ValueError):
        return None
    return cues


def _save_transcription_cache(path: Path, cues: list[SubtitleCue]) -> None:
    write_json_atomic(
        path,
        {
            "version": TRANSCRIPTION_CACHE_VERSION,
            "cues": [
                {
                    "index": cue.index,
                    "start_ms": cue.start_ms,
                    "end_ms": cue.end_ms,
                    "text": cue.text,
                }
                for cue in cues
            ],
        },
    )


def transcribe_with_faster_whisper(
    audio_path: Path,
    source_language: str | None,
    model_size: str,
    progress: ProgressCallback,
    processing_device: str = AUTO_DEVICE,
    stop_event: threading.Event | None = None,
) -> list[SubtitleCue]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install -r requirements-transcription.txt"
        ) from error

    selected_device = normalize_processing_device(processing_device)
    device, compute_type = _preferred_whisper_runtime(selected_device)
    try:
        return _transcribe_with_runtime(
            WhisperModel,
            audio_path,
            source_language,
            model_size,
            device,
            compute_type,
            progress,
            stop_event,
        )
    except Exception as error:
        if device != "cuda" or selected_device != AUTO_DEVICE or isinstance(error, TaskCancelledError):
            raise
        progress(f"CUDA transcription failed: {error}. Falling back to CPU...")
        return _transcribe_with_runtime(
            WhisperModel,
            audio_path,
            source_language,
            model_size,
            "cpu",
            "int8",
            progress,
            stop_event,
        )


def _transcribe_with_runtime(
    whisper_model_class,
    audio_path: Path,
    source_language: str | None,
    model_size: str,
    device: str,
    compute_type: str,
    progress: ProgressCallback,
    stop_event: threading.Event | None = None,
) -> list[SubtitleCue]:
    progress(f"Loading Whisper model: {model_size} ({device.upper()})")
    model = whisper_model_class(model_size, device=device, compute_type=compute_type)
    segments, _info = model.transcribe(
        str(audio_path),
        language=source_language,
        vad_filter=True,
        beam_size=5,
    )

    cues: list[SubtitleCue] = []
    for index, segment in enumerate(segments, start=1):
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelledError()
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


def _preferred_whisper_runtime(processing_device: str = AUTO_DEVICE) -> tuple[str, str]:
    return resolve_whisper_runtime(processing_device)


def _normalize_language(value: str, auto_value: str) -> str:
    normalized = value.strip().lower()
    return normalized or auto_value


def cues_to_script(cues: list[SubtitleCue]) -> str:
    return "\n".join(cue.text.strip() for cue in cues if cue.text.strip())
