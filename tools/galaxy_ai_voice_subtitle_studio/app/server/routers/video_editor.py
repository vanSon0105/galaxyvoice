"""Web API for the lightweight video editor workspace."""
from __future__ import annotations

import mimetypes
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...batch.omnivoice_adapter import OmniVoiceBatchAdapter
from ...batch.system_voice_adapter import SystemVoiceBatchAdapter
from ...common.cache import default_cache_dir
from ...common.config import default_config_path, load_app_config
from ...common.processes import managed_media_processes
from ...omnivoice.client import OmniVoiceWorkerClient
from ...omnivoice.runtime import OmniVoiceRuntime
from ...omnivoice.task_runner import shared_omnivoice_task_coordinator
from ...omnivoice.worker_pool import get_shared_worker_client
from ...project_graph.integrations import register_media_result
from ...project_graph.runtime import project_graph_service
from ...runtime.jobs import TaskContext
from ...studio.execution import clamp_speech_workers
from ...studio.models import StudioVoiceSelection
from ...studio.render_cache import SpeechRenderCache
from ...video_editor.service import (
    EDITOR_AUDIO_MODES,
    EDITOR_ENCODERS,
    EDITOR_FPS_OPTIONS,
    EDITOR_RESOLUTIONS,
    EditorExportOptions,
    EditorMediaClip,
    EditorVideoSegment,
    load_editor_subtitles,
    probe_audio_duration,
    probe_editor_media,
)
from ...video_editor.condensation import CueCondensationService, CueCondensationSpec
from ...video_editor.speech import (
    EditorSpeechCueSpec,
    EditorSpeechItemResult,
    EditorSpeechResult,
    EditorSpeechService,
    EditorSpeechSpec,
)
from ...voice.srt import SubtitleCue
from ...voice.translator import (
    AITranslationOptions,
    default_translation_api_key,
    default_translation_provider,
    resolve_translation_options,
    validate_translation_options,
)
from ...runtime.resources import resource_keys_for_device
from ...voice.tts import EDGE_ENGINE_CODE, create_tts_engine, tts_engine_codes
from ..event_bus import event_bus
from ..tasks import TaskRecord, run_task, task_registry

router = APIRouter(prefix="/api/editor", tags=["video-editor"])

_sources: dict[str, Path] = {}
_source_order: deque[str] = deque()
_sources_lock = threading.Lock()
_MAX_REGISTERED_SOURCES = 48
_speech_task_coordinator = shared_omnivoice_task_coordinator


class LoadRequest(BaseModel):
    path: str
    kind: str


class CueRequest(BaseModel):
    path: str
    duration_ms: int | None = Field(None, gt=0)


class CuePayload(BaseModel):
    index: int = Field(ge=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str

    def to_cue(self) -> SubtitleCue:
        if self.end_ms <= self.start_ms:
            raise ValueError("Thời điểm kết thúc phụ đề phải sau thời điểm bắt đầu.")
        return SubtitleCue(self.index, self.start_ms, self.end_ms, self.text)


class EditorSpeechVoiceRequest(BaseModel):
    source: str = "auto"
    profile_id: str = ""
    reference_audio: str = ""
    reference_text: str = ""
    instruction: str = ""


class EditorSpeechCueRequest(BaseModel):
    item_id: str
    track_id: str
    cue_id: str
    start_ms: int = Field(ge=0)
    end_ms: int | None = Field(None, gt=0)
    text: str
    language: str = ""


class EditorSpeechRequest(BaseModel):
    job_id: str
    project_id: str
    title: str = "Editor speech"
    output_dir: str
    engine_id: str = "omnivoice"
    model_id: str = "k2-fsa/OmniVoice"
    device: str = "auto"
    language: str = "vi"
    speed: float = 1.0
    max_workers: int = 3
    voice_revision: int = Field(1, ge=1)
    voice: EditorSpeechVoiceRequest = Field(default_factory=EditorSpeechVoiceRequest)
    engine_options: dict[str, Any] = Field(default_factory=dict)
    cues: list[EditorSpeechCueRequest] = Field(default_factory=list)


class EditorCondensationRequest(BaseModel):
    project_id: str = ""
    track_id: str
    cue_id: str
    text: str
    language: str = "vi"
    cue_duration_ms: int = Field(gt=0)
    audio_duration_ms: int = Field(gt=0)


class VideoSegmentPayload(BaseModel):
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)

    def to_segment(self) -> EditorVideoSegment:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("Điểm kết thúc đoạn video phải sau điểm bắt đầu.")
        return EditorVideoSegment(self.source_start_ms, self.source_end_ms)


class MediaClipPayload(BaseModel):
    path: str
    timeline_start_ms: int = Field(ge=0)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    track_order: int = Field(ge=0)
    volume: int = Field(100, ge=0, le=200)
    has_audio: bool = True

    def to_clip(self, label: str) -> EditorMediaClip:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("Điểm kết thúc clip phải sau điểm bắt đầu.")
        return EditorMediaClip(
            path=_existing_file(self.path, label),
            timeline_start_ms=self.timeline_start_ms,
            source_start_ms=self.source_start_ms,
            source_end_ms=self.source_end_ms,
            track_order=self.track_order,
            volume=self.volume,
            has_audio=self.has_audio,
        )


class ExportRequest(BaseModel):
    galaxy_project_id: str = ""
    video_path: str
    output_dir: str
    project_name: str = ""
    audio_path: str | None = None
    cues: list[CuePayload] = Field(default_factory=list)
    segments: list[VideoSegmentPayload] = Field(default_factory=list)
    audio_offset_ms: int = Field(0, ge=0)
    audio_mode: str = "mix"
    source_volume: int = Field(100, ge=0, le=200)
    external_volume: int = Field(100, ge=0, le=200)
    resolution: str = "original"
    fps: str = "source"
    encoder: str = "auto"
    quality: int = Field(20, ge=14, le=32)
    subtitle_font_size: int = Field(22, ge=10, le=72)
    subtitle_margin: int = Field(36, ge=0, le=500)
    video_clips: list[MediaClipPayload] = Field(default_factory=list)
    audio_clips: list[MediaClipPayload] = Field(default_factory=list)


def _existing_file(raw_path: str, label: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise HTTPException(status_code=422, detail=f"{label} không tồn tại.")
    return path


def _register_source(path: Path) -> tuple[str, str]:
    source_id = uuid.uuid4().hex
    with _sources_lock:
        _sources[source_id] = path
        _source_order.append(source_id)
        while len(_source_order) > _MAX_REGISTERED_SOURCES:
            _sources.pop(_source_order.popleft(), None)
    return source_id, f"/api/editor/source/{source_id}"


def _progress(record: TaskRecord):
    def report(message: str) -> None:
        task_registry.report(record.task_id, message)

    return report


def _omnivoice_runtime() -> OmniVoiceRuntime:
    return OmniVoiceRuntime.default()


def _omnivoice_worker_client() -> OmniVoiceWorkerClient:
    worker_path = Path(__file__).resolve().parents[2] / "omnivoice" / "worker.py"
    return get_shared_worker_client(_omnivoice_runtime(), worker_path)


def _settings_path(request: Request) -> Path:
    configured = getattr(request.app.state, "settings_path", None)
    return Path(configured) if configured is not None else default_config_path()


def _editor_speech_spec(body: EditorSpeechRequest) -> EditorSpeechSpec:
    return EditorSpeechSpec(
        job_id=body.job_id.strip(),
        project_id=body.project_id.strip(),
        title=body.title.strip() or "Editor speech",
        output_dir=body.output_dir.strip(),
        engine_id=body.engine_id.strip() or "omnivoice",
        model_id=body.model_id.strip() or "k2-fsa/OmniVoice",
        device=body.device.strip() or "auto",
        language=body.language.strip() or "vi",
        speed=body.speed,
        max_workers=clamp_speech_workers(body.max_workers),
        voice_revision=body.voice_revision,
        voice=StudioVoiceSelection(**body.voice.model_dump()),
        engine_options=dict(body.engine_options),
        cues=tuple(
            EditorSpeechCueSpec(
                item_id=cue.item_id.strip(),
                track_id=cue.track_id.strip(),
                cue_id=cue.cue_id.strip(),
                start_ms=cue.start_ms,
                text=cue.text,
                language=cue.language.strip(),
                end_ms=cue.end_ms or 0,
            )
            for cue in body.cues
        ),
    )


@router.post("/speech")
def start_speech(body: EditorSpeechRequest, request: Request) -> dict[str, str]:
    spec = _editor_speech_spec(body)
    try:
        spec.validate()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    is_omnivoice = spec.engine_id == "omnivoice"
    is_system_voice = spec.engine_id in tts_engine_codes()
    if not is_omnivoice and not is_system_voice:
        raise HTTPException(status_code=422, detail=f"Engine chưa được cài: {spec.engine_id}")
    resource_keys = (
        resource_keys_for_device(spec.device)
        if is_omnivoice
        else (("network",) if spec.engine_id == EDGE_ENGINE_CODE else ())
    )
    record = task_registry.create(
        "editor-speech",
        capability_id=f"tts.{spec.engine_id}",
        pausable=True,
        project_id=spec.project_id,
        workflow_id=spec.job_id,
        resource_keys=resource_keys,
        recovery_route="/editor",
        recovery_hint="Mở Dựng video và tạo lại audio từ phụ đề.",
    )
    if is_omnivoice:
        record.on_cancel = lambda: _speech_task_coordinator.cancel(record.task_id)

    completed = 0
    failed = 0
    service = EditorSpeechService(
        render_cache=SpeechRenderCache(default_cache_dir() / "speech-renders")
    )

    def item_finished(item: EditorSpeechItemResult) -> None:
        nonlocal completed, failed
        completed += int(item.status == "done")
        failed += int(item.status == "failed")
        event_bus.emit(
            {
                "type": "event",
                "kind": "editor_speech_item",
                "payload": {
                    "job_id": spec.job_id,
                    "task_id": record.task_id,
                    **item.to_payload(),
                    "completed": completed,
                    "failed": failed,
                    "total": len(spec.cues),
                },
            }
        )

    def execute(context: TaskContext) -> EditorSpeechResult:
        callbacks = {
            "progress": lambda message, value: context.report(message, progress=value),
            "checkpoint": context.save_checkpoint,
            "control": context.wait_if_paused,
            "stop_event": record.stop_event,
            "item_finished": item_finished,
        }
        if is_omnivoice:
            return _speech_task_coordinator.run(
                record.task_id,
                record.stop_event,
                lambda client: service.execute(
                    spec,
                    OmniVoiceBatchAdapter(client, _omnivoice_runtime().profiles_dir),
                    **callbacks,
                ),
                client_factory=_omnivoice_worker_client,
            )
        return service.execute(
            spec,
            SystemVoiceBatchAdapter(
                create_tts_engine(spec.engine_id),
                str(spec.engine_options.get("voice_name") or ""),
            ),
            **callbacks,
        )

    configured = getattr(request.app.state, "settings_path", None)
    graph_service = project_graph_service(Path(configured) if configured is not None else None)

    def serialize(result: EditorSpeechResult) -> dict[str, Any]:
        register_media_result(
            graph_service,
            project_id=spec.project_id,
            workspace="editor",
            owner_id=spec.job_id,
            label=spec.title,
            sources=(),
            outputs=tuple(
                (f"generated_voice:{item.item_id}", item.wav_path)
                for item in result.items
                if item.status == "done" and item.wav_path
            ),
            metadata={"workflow": "subtitle-speech", "cue_count": len(spec.cues)},
        )
        return result.to_payload()

    task_registry.submit(record, execute, serialize)
    return {"job_id": spec.job_id, "task_id": record.task_id}


@router.post("/speech/condense")
def start_condensation(body: EditorCondensationRequest, request: Request) -> dict[str, str]:
    spec = CueCondensationSpec(
        track_id=body.track_id.strip(),
        cue_id=body.cue_id.strip(),
        text=body.text,
        language=body.language.strip() or "vi",
        cue_duration_ms=body.cue_duration_ms,
        audio_duration_ms=body.audio_duration_ms,
    )
    try:
        spec.validate()
        config = load_app_config(_settings_path(request))
        provider = config.ai_provider or default_translation_provider()
        options = resolve_translation_options(
            AITranslationOptions(
                source_language=spec.language,
                target_language=spec.language,
                provider=provider,
                api_key=default_translation_api_key(provider),
                model=config.ai_model,
                base_url=config.ai_base_url,
            )
        )
        validate_translation_options(options)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    record = task_registry.create(
        "editor-condensation",
        capability_id=f"ai.{options.provider}",
        project_id=body.project_id.strip(),
        resource_keys=("network",),
        recovery_route="/editor",
        recovery_hint="Chọn lại cue bị tràn để tạo đề xuất rút gọn.",
    )
    service = CueCondensationService()

    def execute(context: TaskContext):
        context.report("Đang tạo đề xuất rút gọn...", progress=0.05)
        result = service.propose(spec, options, stop_event=record.stop_event)
        context.report("Đã tạo đề xuất để xem trước.", progress=1.0)
        return result

    task_registry.submit(record, execute, lambda result: result.to_payload())
    return {"task_id": record.task_id}


@router.post("/load")
def load_media(body: LoadRequest) -> dict[str, Any]:
    kind = body.kind.strip().lower()
    if kind not in {"video", "audio"}:
        raise HTTPException(status_code=422, detail="Loại media phải là video hoặc audio.")
    path = _existing_file(body.path, "Tệp media")
    try:
        if kind == "video":
            info = probe_editor_media(path)
            payload = {
                "duration_seconds": info.duration_seconds,
                "width": info.width,
                "height": info.height,
                "fps": info.fps,
                "has_audio": info.has_audio,
            }
        else:
            payload = {
                "duration_seconds": probe_audio_duration(path),
                "width": 0,
                "height": 0,
                "fps": 0,
                "has_audio": True,
            }
    except RuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    source_id, url = _register_source(path)
    return {"source_id": source_id, "url": url, "name": path.name, "path": str(path), "kind": kind, **payload}


@router.get("/source/{source_id}")
def stream_source(source_id: str) -> FileResponse:
    with _sources_lock:
        path = _sources.get(source_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Nguồn media không còn khả dụng.")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


@router.post("/cues")
def parse_cues(body: CueRequest) -> dict[str, Any]:
    path = _existing_file(body.path, "Tệp SRT")
    try:
        cues = load_editor_subtitles(path, body.duration_ms)
    except (RuntimeError, UnicodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "name": path.name,
        "path": str(path),
        "cues": [
            {"index": cue.index, "start_ms": cue.start_ms, "end_ms": cue.end_ms, "text": cue.text}
            for cue in cues
        ],
    }


@router.post("/export")
def start_export(body: ExportRequest, request: Request) -> dict[str, str]:
    video_path = _existing_file(body.video_path, "Video đầu vào")
    audio_path = _existing_file(body.audio_path, "Audio đầu vào") if body.audio_path else None
    if not body.output_dir.strip():
        raise HTTPException(status_code=422, detail="Chọn thư mục xuất trước khi dựng video.")
    if body.resolution not in EDITOR_RESOLUTIONS or body.fps not in EDITOR_FPS_OPTIONS:
        raise HTTPException(status_code=422, detail="Thiết lập hình ảnh không hợp lệ.")
    if body.encoder not in EDITOR_ENCODERS or body.audio_mode not in EDITOR_AUDIO_MODES:
        raise HTTPException(status_code=422, detail="Thiết lập xuất video không hợp lệ.")
    try:
        cues = tuple(item.to_cue() for item in body.cues)
        segments = tuple(item.to_segment() for item in body.segments)
        video_clips = tuple(item.to_clip("Video clip") for item in body.video_clips)
        audio_clips = tuple(item.to_clip("Audio clip") for item in body.audio_clips)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    options = EditorExportOptions(
        video_path=video_path,
        output_dir=Path(body.output_dir).expanduser(),
        project_name=body.project_name,
        audio_path=audio_path,
        subtitle_cues=cues,
        video_segments=segments,
        video_clips=video_clips,
        audio_clips=audio_clips,
        audio_offset_ms=body.audio_offset_ms,
        audio_mode=body.audio_mode,
        source_volume=body.source_volume,
        external_volume=body.external_volume,
        resolution=body.resolution,
        fps=body.fps,
        encoder=body.encoder,
        quality=body.quality,
        subtitle_font_size=body.subtitle_font_size,
        subtitle_margin=body.subtitle_margin,
    )
    record = task_registry.create(
        "video-editor",
        capability_id="media.ffmpeg",
        resource_keys=resource_keys_for_device(
            "cuda" if "nvenc" in body.encoder.lower() else "cpu"
        ),
    )
    record.on_cancel = lambda: managed_media_processes.terminate_task(record.task_id)
    configured = getattr(request.app.state, "settings_path", None)
    graph_service = project_graph_service(Path(configured) if configured is not None else None)
    source_assets = tuple(dict.fromkeys(
        [("source_video", str(video_path))]
        + ([("source_audio", str(audio_path))] if audio_path is not None else [])
        + [("source_video", str(clip.path)) for clip in video_clips]
        + [("source_audio", str(clip.path)) for clip in audio_clips]
    ))

    def run_export():
        from ...video_editor.service import export_editor_video

        return export_editor_video(
            options,
            progress=_progress(record),
            cancellation=record.stop_event,
            task_id=record.task_id,
        )

    def serialize(result: Any) -> dict[str, Any]:
        register_media_result(
            graph_service,
            project_id=body.galaxy_project_id,
            workspace="editor",
            owner_id=record.task_id,
            label=body.project_name or result.video_path.stem,
            sources=source_assets,
            outputs=tuple(
                (role, str(path))
                for role, path in (
                    ("edited_video", result.video_path),
                    ("subtitle", result.subtitle_path),
                    ("manifest", result.manifest_path),
                )
                if path is not None
            ),
            metadata={"resolution": body.resolution, "fps": body.fps},
        )
        return {
            "project_dir": str(result.project_dir),
            "video_path": str(result.video_path),
            "video_url": f"/api/files/task/{record.task_id}/{result.video_path.name}",
            "subtitle_path": str(result.subtitle_path) if result.subtitle_path else None,
            "manifest_path": str(result.manifest_path),
            "warnings": list(result.warnings),
        }

    run_task(record, run_export, serialize)
    return {"task_id": record.task_id}


def reset_editor_sources() -> None:
    with _sources_lock:
        _sources.clear()
        _source_order.clear()
