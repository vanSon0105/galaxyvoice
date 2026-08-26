"""Video Dubbing workspace endpoints: TTS generation, audio extraction,
subtitle transcription/translation with an editable draft, and export.

All business logic lives in the shared service modules (app/voice/*); this
router only adapts them to the web task protocol.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...common.config import default_config_path, load_app_config
from ...common.errors import TaskCancelledError
from ...voice.engine import GenerationOptions, generate_package
from ...voice.media import MediaExtractionOptions, extract_audio_from_video
from ...voice.srt import parse_srt
from ...voice.transcription import (
    VideoSubtitleDraft,
    VideoSubtitleOptions,
    export_subtitle_package,
    prepare_subtitles_from_video,
)
from ...voice.translator import (
    AITranslationOptions,
    default_translation_api_key,
    default_translation_base_url,
    default_translation_model,
    fetch_translation_models,
    normalize_translation_provider,
    translate_script_text,
    validate_translation_options,
)
from ...voice.tts import create_tts_engine, tts_engine_codes
from ..event_bus import event_bus
from ...runtime.resources import resource_keys_for_device
from ..tasks import CANCELLED, DONE, FAILED, TaskRecord, run_task, task_registry

router = APIRouter(prefix="/api/voice")

# Session-scoped draft store keeps one
# subtitle draft at a time; a new successful transcription replaces the old.
_drafts: dict[str, VideoSubtitleDraft] = {}
_draft_edits: dict[str, dict[str, str]] = {}
_drafts_lock = threading.Lock()


class GenerateRequest(BaseModel):
    text: str
    output_dir: str
    project_name: str = ""
    engine: str = ""
    voice_name: str | None = None
    rate: int = 0
    volume: int = 100
    pause_ms: int = 250
    max_chars: int = 160
    export_mp3: bool = True
    keep_segments: bool = True
    # Optional in-flow script translation: the
    # script is translated to the target language before synthesis).
    source_language: str = "auto"
    target_language: str = "none"
    ai_provider: str = ""
    ai_model: str = ""
    ai_base_url: str = ""
    ai_api_key: str = ""


class ExtractAudioRequest(BaseModel):
    video_path: str
    output_dir: str
    project_name: str = ""
    export_wav: bool = True
    export_mp3: bool = True


class TranscribeRequest(BaseModel):
    video_path: str
    output_dir: str
    project_name: str = ""
    source_language: str = "auto"
    target_language: str = "vi"
    whisper_model: str = "base"
    processing_device: str = "auto"
    ai_provider: str = ""
    ai_model: str = ""
    ai_base_url: str = ""
    ai_api_key: str = ""
    translation_batch_size: int = 2
    translation_workers: int = 6


class DraftEditRequest(BaseModel):
    source_srt: str | None = None
    translated_srt: str | None = None


class DraftExportRequest(BaseModel):
    output_dir: str = ""
    project_name: str = ""


class TranslationModelsRequest(BaseModel):
    provider: str
    api_key: str = ""
    base_url: str = ""


def _config() -> Any:
    return load_app_config(default_config_path())


def _progress(record: TaskRecord):
    def report(message: str) -> None:
        event_bus.emit({"type": "progress", "task_id": record.task_id, "message": message})

    return report


def _generation_result_dict(result: Any) -> dict[str, Any]:
    return {
        "project_dir": str(result.project_dir),
        "wav_path": str(result.wav_path),
        "srt_path": str(result.srt_path),
        "mp3_path": str(result.mp3_path) if result.mp3_path else None,
        "manifest_path": str(result.manifest_path),
        "cue_count": result.cue_count,
        "total_duration_ms": result.total_duration_ms,
        "warnings": list(result.warnings),
    }


def _media_result_dict(result: Any) -> dict[str, Any]:
    return {
        "project_dir": str(result.project_dir),
        "wav_path": str(result.wav_path) if result.wav_path else None,
        "mp3_path": str(result.mp3_path) if result.mp3_path else None,
        "manifest_path": str(result.manifest_path),
        "warnings": list(result.warnings),
    }


def _store_draft(task_id: str, draft: VideoSubtitleDraft) -> None:
    with _drafts_lock:
        for old_id, old_draft in list(_drafts.items()):
            if old_id != task_id:
                old_draft.cleanup()
        _drafts.clear()
        _draft_edits.clear()
        _drafts[task_id] = draft


def _draft_payload(task_id: str, draft: VideoSubtitleDraft) -> dict[str, Any]:
    edits = _draft_edits.get(task_id, {})
    return {
        "task_id": task_id,
        "source_video": str(draft.source_video),
        "project_name": draft.project_name,
        "source_language": draft.source_language,
        "target_language": draft.target_language,
        "whisper_model": draft.whisper_model,
        "ai_provider": draft.ai_provider,
        "ai_model": draft.ai_model,
        "ai_base_url": draft.ai_base_url,
        "source_srt": edits.get("source_srt", draft.source_srt_text),
        "translated_srt": (
            edits.get("translated_srt", draft.translated_srt_text)
            if draft.translated_cues is not None
            else None
        ),
        "script_text": draft.script_text,
        "script_language": draft.script_language,
        "warnings": list(draft.warnings),
    }


@router.get("/engines")
def engines() -> list[dict[str, Any]]:
    result = []
    for code in tts_engine_codes():
        engine = create_tts_engine(code)
        result.append(
            {
                "code": code,
                "label": engine.label,
                "available": engine.available(),
                "unavailable_reason": engine.unavailable_reason(),
            }
        )
    return result


@router.get("/voices")
def voices(engine: str = "") -> list[dict[str, Any]]:
    engine_code = engine.strip() or _config().tts_engine
    tts = create_tts_engine(engine_code)
    return [
        {
            "name": voice.name,
            "culture": voice.culture,
            "gender": voice.gender,
            "age": voice.age,
        }
        for voice in tts.list_voices()
    ]


@router.post("/translation-models")
def translation_models(request: TranslationModelsRequest) -> dict[str, Any]:
    provider = normalize_translation_provider(request.provider)
    try:
        models = fetch_translation_models(
            provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"provider": provider, "models": list(models)}


def _same_language(source: str, target: str) -> bool:
    return source != "auto" and source == target


@router.post("/generate")
def generate(request: GenerateRequest) -> dict[str, Any]:
    if not request.text.strip():
        raise HTTPException(status_code=422, detail="Script is empty.")
    output_dir = Path(request.output_dir).expanduser()
    engine_code = request.engine.strip() or _config().tts_engine
    tts = create_tts_engine(engine_code)
    source_language = request.source_language.strip().lower() or "auto"
    target_language = request.target_language.strip().lower() or "none"

    translation_options: AITranslationOptions | None = None
    if target_language != "none" and not _same_language(source_language, target_language):
        provider = normalize_translation_provider(request.ai_provider)
        translation_options = AITranslationOptions(
            source_language=source_language,
            target_language=target_language,
            provider=provider,
            api_key=request.ai_api_key or default_translation_api_key(provider),
            model=request.ai_model or default_translation_model(provider),
            base_url=request.ai_base_url or default_translation_base_url(provider),
        )
        validate_translation_options(translation_options)

    record = task_registry.create("generate")
    event_bus.emit({"type": "task", "task_id": record.task_id, "status": "running"})
    state: dict[str, Any] = {"translated_text": None}

    def run_generate():
        report = _progress(record)
        text = request.text
        if translation_options is not None:
            report(f"Dịch kịch bản sang {target_language}...")
            text = translate_script_text(
                request.text,
                translation_options,
                stop_event=record.stop_event,
            )
            state["translated_text"] = text
        return generate_package(
            GenerationOptions(
                text=text,
                output_dir=output_dir,
                project_name=request.project_name,
                voice_name=request.voice_name,
                rate=request.rate,
                volume=request.volume,
                pause_ms=request.pause_ms,
                max_chars=request.max_chars,
                export_mp3=request.export_mp3,
                keep_segments=request.keep_segments,
            ),
            tts=tts,
            progress=report,
            stop_event=record.stop_event,
        )

    def serialize(result: Any) -> dict[str, Any]:
        payload = _generation_result_dict(result)
        payload["translated_text"] = state["translated_text"]
        payload["target_language"] = (
            target_language if state["translated_text"] is not None else None
        )
        return payload

    run_task(record, run_generate, serialize)
    return {"task_id": record.task_id}


@router.post("/extract-audio")
def extract_audio(request: ExtractAudioRequest) -> dict[str, Any]:
    if not request.video_path.strip():
        raise HTTPException(status_code=422, detail="Chọn video trước khi trích audio.")
    if not request.export_wav and not request.export_mp3:
        raise HTTPException(status_code=422, detail="Chọn WAV, MP3 hoặc cả hai.")
    options = MediaExtractionOptions(
        video_path=Path(request.video_path).expanduser(),
        output_dir=Path(request.output_dir).expanduser(),
        project_name=request.project_name,
        export_wav=request.export_wav,
        export_mp3=request.export_mp3,
    )
    record = task_registry.create("extract-audio")
    event_bus.emit({"type": "task", "task_id": record.task_id, "status": "running"})
    run_task(
        record,
        lambda: extract_audio_from_video(
            options,
            progress=_progress(record),
            stop_event=record.stop_event,
        ),
        _media_result_dict,
    )
    return {"task_id": record.task_id}


@router.post("/transcribe")
def transcribe(request: TranscribeRequest) -> dict[str, Any]:
    if not request.video_path.strip():
        raise HTTPException(status_code=422, detail="Chọn video trước khi tạo phụ đề.")
    options = VideoSubtitleOptions(
        video_path=Path(request.video_path).expanduser(),
        output_dir=Path(request.output_dir).expanduser(),
        project_name=request.project_name,
        source_language=request.source_language,
        target_language=request.target_language,
        whisper_model=request.whisper_model,
        processing_device=request.processing_device,
        ai_provider=request.ai_provider,
        ai_model=request.ai_model,
        ai_base_url=request.ai_base_url,
        ai_api_key=request.ai_api_key,
        translation_batch_size=request.translation_batch_size,
        translation_workers=request.translation_workers,
    )
    record = task_registry.create(
        "transcribe",
        capability_id="asr.faster-whisper",
        resumable=True,
        resource_keys=resource_keys_for_device(request.processing_device),
    )
    event_bus.emit({"type": "task", "task_id": record.task_id, "status": "running"})

    def run_transcribe() -> dict[str, Any]:
        draft = prepare_subtitles_from_video(
            options,
            progress=_progress(record),
            stop_event=record.stop_event,
        )
        _store_draft(record.task_id, draft)
        event_bus.emit(
            {"type": "event", "kind": "draft_ready", "payload": {"task_id": record.task_id}}
        )
        return _draft_payload(record.task_id, draft)

    run_task(record, run_transcribe)
    return {"task_id": record.task_id}


@router.get("/draft/{task_id}")
def get_draft(task_id: str) -> dict[str, Any]:
    with _drafts_lock:
        draft = _drafts.get(task_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản phụ đề nháp")
    return _draft_payload(task_id, draft)


@router.put("/draft/{task_id}")
def update_draft(task_id: str, request: DraftEditRequest) -> dict[str, Any]:
    with _drafts_lock:
        draft = _drafts.get(task_id)
        existing = _draft_edits.get(task_id, {})
    if draft is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản phụ đề nháp")
    source_text = (
        request.source_srt
        if request.source_srt is not None
        else existing.get("source_srt", draft.source_srt_text)
    )
    translated_text = (
        request.translated_srt
        if request.translated_srt is not None
        else existing.get("translated_srt", draft.translated_srt_text)
    )
    try:
        source_cues = parse_srt(source_text)
        translated_cues = parse_srt(translated_text) if translated_text is not None else None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"SRT không hợp lệ: {error}")
    if translated_cues is not None and len(source_cues) != len(translated_cues):
        raise HTTPException(
            status_code=422,
            detail="Sub gốc và Sub dịch phải có cùng số dòng.",
        )
    with _drafts_lock:
        edits = _draft_edits.setdefault(task_id, {})
        if request.source_srt is not None:
            edits["source_srt"] = source_text.rstrip("\r\n") + "\n"
        if request.translated_srt is not None:
            edits["translated_srt"] = translated_text.rstrip("\r\n") + "\n"
    return _draft_payload(task_id, draft)


@router.post("/draft/{task_id}/export")
def export_draft(task_id: str, request: DraftExportRequest) -> dict[str, Any]:
    with _drafts_lock:
        draft = _drafts.get(task_id)
        edits = _draft_edits.get(task_id, {})
    if draft is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản phụ đề nháp")
    config = _config()
    output_dir = Path(request.output_dir or config.output_dir or ".").expanduser()
    result = export_subtitle_package(
        draft,
        output_dir,
        request.project_name or None,
        source_srt_text=edits.get("source_srt"),
        translated_srt_text=edits.get("translated_srt"),
    )
    event_bus.emit(
        {"type": "event", "kind": "subtitle_exported", "payload": {"task_id": task_id}}
    )
    return {
        "project_dir": str(result.project_dir),
        "audio_path": str(result.audio_path),
        "source_srt_path": str(result.source_srt_path),
        "translated_srt_path": str(result.translated_srt_path) if result.translated_srt_path else None,
        "manifest_path": str(result.manifest_path),
        "cue_count": result.cue_count,
        "script_text": result.script_text,
        "script_language": result.script_language,
        "warnings": list(result.warnings),
    }
