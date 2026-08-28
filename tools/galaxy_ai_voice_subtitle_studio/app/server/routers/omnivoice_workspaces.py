"""OmniVoice workspaces endpoints: repository, gallery, transcripts,
source imports, longform documents (stories/audiobook) and rendering.

The longform document lives in a server-side session and every edit op is
applied through the same EditableLongformDocument class the workspace service
uses, so the two UIs can never diverge on editing semantics.
"""
from __future__ import annotations

import mimetypes
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...common.cache import read_json
from ...common.errors import TaskCancelledError
from ...omnivoice.client import OmniVoiceWorkerClient
from ...omnivoice.models import AUTO_MODE, DEFAULT_MODEL_ID, OmniVoiceGenerationOptions
from ...omnivoice.profiles import list_voice_profiles
from ...omnivoice.runtime import OmniVoiceRuntime, load_supported_language_ids
from ...omnivoice.task_runner import shared_omnivoice_task_coordinator
from ...omnivoice.worker_pool import get_shared_worker_client
from ...omnivoice.workspaces.common.repository import WorkspaceRepository
from ...project_graph.integrations import register_dubbing_project, register_longform_project
from ...project_graph.runtime import project_graph_service
from ...project_graph.service import ProjectGraphService
from ...omnivoice.workspaces.dubbing.model import (
    DubbingFitPolicy,
    DubbingSegment,
    build_dubbing_segments,
    build_dubbing_quality_report,
    validate_dubbing_segments,
)
from ...omnivoice.workspaces.dubbing.project import (
    DubbingProject,
    DubbingProjectRepository,
    DubbingRevisionConflict,
)
from ...omnivoice.workspaces.dubbing.service import render_dubbing_project
from ...omnivoice.workspaces.editable import EditableLongformDocument
from ...omnivoice.workspaces.gallery import list_voice_archetypes, voice_archetype_categories
from ...omnivoice.workspaces.imports import load_audiobook_source
from ...omnivoice.workspaces.longform_project import (
    LongformProject,
    LongformProjectRepository,
    LongformRevisionConflict,
)
from ...omnivoice.workspaces.longform_service import (
    attach_longform_result,
    create_longform_document,
    document_from_project,
    preview_plan,
    save_longform_project as save_longform_project_service,
)
from ...omnivoice.workspaces.renderer import (
    find_resumable_workspace_jobs,
    render_longform_plan,
)
from ...omnivoice.workspaces.transcripts import TranscriptStore
from ...voice.srt import parse_srt, render_srt
from ...voice.translator import (
    AITranslationOptions,
    default_translation_api_key,
    default_translation_base_url,
    default_translation_model,
    normalize_translation_provider,
    translate_cues,
    translation_checkpoint_path,
    validate_translation_options,
)
from ..event_bus import event_bus
from ...runtime.resources import resource_keys_for_device
from ..tasks import TaskRecord, run_task, task_registry

router = APIRouter(prefix="/api/workspaces")

GALLERY_PAGE_SIZE = 120
RESUME_CACHE_TTL_SECONDS = 60.0

_documents: dict[str, EditableLongformDocument] = {}
_documents_lock = threading.Lock()
_resume_cache: dict[str, Any] = {"at": 0.0, "value": None}
_task_coordinator = shared_omnivoice_task_coordinator


def _runtime() -> OmniVoiceRuntime:
    return OmniVoiceRuntime.default()


def _worker_path() -> Path:
    """app/server/routers/omnivoice_workspaces.py -> app/omnivoice/worker.py"""
    return Path(__file__).resolve().parents[2] / "omnivoice" / "worker.py"


def _worker_client() -> OmniVoiceWorkerClient:
    return get_shared_worker_client(_runtime(), _worker_path())


def _settings_path(request: Request) -> Path:
    from ...common.config import default_config_path

    path = getattr(request.app.state, "settings_path", None)
    return Path(path) if path is not None else default_config_path()


def _repository(request: Request) -> WorkspaceRepository:
    return WorkspaceRepository(_settings_path(request).with_name("omnivoice_workspaces.json"))


def _project_graph(request: Request) -> ProjectGraphService:
    return project_graph_service(_settings_path(request))


def _transcripts(request: Request) -> TranscriptStore:
    return TranscriptStore(_settings_path(request).with_name("transcriptions.json"))


def _dubbing_repository(request: Request) -> DubbingProjectRepository:
    return DubbingProjectRepository(_settings_path(request).with_name("dubbing_projects.json"))


def _longform_repository(request: Request) -> LongformProjectRepository:
    return LongformProjectRepository(_settings_path(request).with_name("longform_projects.json"))


def _progress(record: TaskRecord):
    def report(message: str) -> None:
        event_bus.emit({"type": "progress", "task_id": record.task_id, "message": message})

    return report


# ---------- Repository ----------


@router.get("/projects")
def list_projects(request: Request, workspace: str = "") -> list[dict[str, Any]]:
    return [_project_dict(item) for item in _repository(request).list_projects(workspace)]


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request) -> dict[str, Any]:
    item = _repository(request).get_project(project_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy project")
    return _project_dict(item)


class SaveProjectRequest(BaseModel):
    workspace: str
    name: str
    payload: dict[str, Any] = {}
    project_id: str = ""


@router.post("/projects")
def save_project(request_body: SaveProjectRequest, request: Request) -> dict[str, Any]:
    try:
        item = _repository(request).save_project(
            workspace=request_body.workspace,
            name=request_body.name,
            payload=request_body.payload,
            project_id=request_body.project_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    event_bus.emit({"type": "event", "kind": "workspace_projects_updated", "payload": {}})
    return _project_dict(item)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, request: Request) -> dict[str, bool]:
    _repository(request).delete_project(project_id)
    event_bus.emit({"type": "event", "kind": "workspace_projects_updated", "payload": {}})
    return {"ok": True}


@router.get("/history")
def list_history(
    request: Request,
    workspace: str = "",
    query: str = "",
    starred_only: bool = False,
) -> list[dict[str, Any]]:
    repository = _repository(request)
    if query.strip() or starred_only:
        items = repository.search_history(query, workspace=workspace, starred_only=starred_only)
    else:
        items = repository.list_history(workspace)
    return [_history_dict(item) for item in items]


class AddHistoryRequest(BaseModel):
    workspace: str
    title: str
    summary: str = ""
    artifact_path: str = ""
    metadata: dict[str, Any] | None = None


@router.post("/history")
def add_history(request_body: AddHistoryRequest, request: Request) -> dict[str, Any]:
    try:
        item = _repository(request).add_history(
            workspace=request_body.workspace,
            title=request_body.title,
            summary=request_body.summary,
            artifact_path=request_body.artifact_path,
            metadata=request_body.metadata,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return _history_dict(item)


class StarRequest(BaseModel):
    starred: bool


@router.patch("/history/{history_id}/starred")
def star_history(history_id: str, request_body: StarRequest, request: Request) -> dict[str, Any]:
    try:
        item = _repository(request).set_history_starred(history_id, request_body.starred)
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy mục lịch sử")
    return _history_dict(item)


@router.delete("/history/{history_id}")
def delete_history(history_id: str, request: Request) -> dict[str, bool]:
    _repository(request).delete_history(history_id)
    return {"ok": True}


@router.delete("/history")
def clear_history(request: Request, workspace: str = "") -> dict[str, bool]:
    _repository(request).clear_history(workspace)
    return {"ok": True}


def _project_dict(item: Any) -> dict[str, Any]:
    return {
        "project_id": item.project_id,
        "workspace": item.workspace,
        "name": item.name,
        "payload": item.payload,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _history_dict(item: Any) -> dict[str, Any]:
    return {
        "history_id": item.history_id,
        "workspace": item.workspace,
        "title": item.title,
        "summary": item.summary,
        "artifact_path": item.artifact_path,
        "metadata": item.metadata,
        "starred": item.starred,
        "created_at": item.created_at,
    }


# ---------- Gallery ----------


@router.get("/gallery/categories")
def gallery_categories() -> list[str]:
    return list(voice_archetype_categories())


@router.get("/gallery")
def gallery(
    query: str = "",
    use_case: str = "",
    language: str = "",
    gender: str = "",
    age: str = "",
    pitch: str = "",
    style: str = "",
    page: int = 1,
    page_size: int = GALLERY_PAGE_SIZE,
) -> dict[str, Any]:
    items = list_voice_archetypes(
        query=query,
        use_case=use_case,
        language=language,
        gender=gender,
        age=age,
        pitch=pitch,
        style=style,
    )
    total = len(items)
    size = max(1, min(int(page_size), GALLERY_PAGE_SIZE))
    start = (max(1, int(page)) - 1) * size
    page_items = items[start : start + size]
    return {
        "total": total,
        "page": max(1, int(page)),
        "page_size": size,
        "items": [
            {
                "archetype_id": item.archetype_id,
                "name": item.name,
                "language": item.language,
                "use_case": item.use_case,
                "instruct": item.instruct,
                "sample_text": item.sample_text,
                "gender": item.gender,
                "age": item.age,
                "pitch": item.pitch,
                "accent": item.accent,
                "style": item.style,
                "featured": item.featured,
            }
            for item in page_items
        ],
    }


# ---------- Transcripts ----------


@router.get("/transcripts")
def transcripts(request: Request, query: str = "") -> list[dict[str, Any]]:
    store = _transcripts(request)
    items = store.search(query) if query.strip() else store.list()
    return [_transcript_dict(item) for item in items]


class AddTranscriptRequest(BaseModel):
    text: str
    language: str = ""
    source_path: str = ""
    source_srt: str = ""
    translated_srt: str = ""


@router.post("/transcripts")
def add_transcript(request_body: AddTranscriptRequest, request: Request) -> dict[str, Any]:
    try:
        item = _transcripts(request).add(
            text=request_body.text,
            language=request_body.language,
            source_path=request_body.source_path,
            source_srt=request_body.source_srt,
            translated_srt=request_body.translated_srt,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return _transcript_dict(item)


@router.delete("/transcripts/{entry_id}")
def delete_transcript(entry_id: str, request: Request) -> dict[str, bool]:
    _transcripts(request).delete(entry_id)
    return {"ok": True}


@router.delete("/transcripts")
def clear_transcripts(request: Request) -> dict[str, bool]:
    _transcripts(request).clear()
    return {"ok": True}


def _transcript_dict(item: Any) -> dict[str, Any]:
    return {
        "entry_id": item.entry_id,
        "text": item.text,
        "language": item.language,
        "source_path": item.source_path,
        "source_srt": item.source_srt,
        "translated_srt": item.translated_srt,
        "created_at": item.created_at,
    }


# ---------- Longform projects ----------


class LongformProjectRequest(BaseModel):
    galaxy_project_id: str = ""
    project_id: str = ""
    expected_revision: int = 0
    name: str = "longform"
    kind: str = "stories"
    stage: str = "source"
    source: str = ""
    document: dict[str, Any] = Field(default_factory=dict)
    language: str = "vi"
    options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_result: dict[str, Any] = Field(default_factory=dict)


@router.get("/longform/projects")
def list_longform_projects(
    request: Request,
    kind: str = "",
    galaxy_project_id: str = "",
) -> list[dict[str, Any]]:
    return [
        item.__dict__
        for item in _longform_repository(request).list(
            kind,
            galaxy_project_id=galaxy_project_id,
        )
    ]


@router.get("/longform/projects/{project_id}")
def get_longform_project(project_id: str, request: Request) -> dict[str, Any]:
    project = _longform_repository(request).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy project Truyện & Sách nói.")
    return project.to_dict()


@router.get("/longform/projects/{project_id}/media/{kind}")
def get_longform_project_media(project_id: str, kind: str, request: Request) -> FileResponse:
    project = _longform_repository(request).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy project Truyện & Sách nói.")
    field = {"wav": "wav_path", "mp3": "mp3_path", "m4b": "m4b_path"}.get(kind)
    if field is None:
        raise HTTPException(status_code=404, detail="Loại media Longform không hợp lệ.")
    return _project_media_response(project.last_result, field)


@router.post("/longform/projects")
def save_longform_project(body: LongformProjectRequest, request: Request) -> dict[str, Any]:
    repository = _longform_repository(request)
    try:
        saved = save_longform_project_service(
            repository,
            galaxy_project_id=body.galaxy_project_id,
            project_id=body.project_id,
            expected_revision=body.expected_revision,
            name=body.name,
            kind=body.kind,
            stage=body.stage,
            source=body.source,
            document=body.document,
            language=body.language,
            options=body.options,
            metadata=body.metadata,
        )
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy project Truyện & Sách nói.",
        ) from error
    except LongformRevisionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    register_longform_project(_project_graph(request), saved)
    return saved.to_dict()


@router.delete("/longform/projects/{project_id}")
def delete_longform_project(project_id: str, request: Request) -> dict[str, bool]:
    _longform_repository(request).delete(project_id)
    return {"ok": True}


# ---------- Source import ----------


class ImportSourceRequest(BaseModel):
    path: str


@router.post("/import-source")
def import_source(request_body: ImportSourceRequest) -> dict[str, Any]:
    path = Path(request_body.path).expanduser()
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy file: {path}")
    try:
        text = load_audiobook_source(path)
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"text": text, "path": str(path)}


# ---------- Longform document session (stories / audiobook) ----------


class CreateDocumentRequest(BaseModel):
    kind: str
    source: str = ""
    document: dict[str, Any] = Field(default_factory=dict)
    language: str = "auto"


@router.post("/document")
def create_document(request_body: CreateDocumentRequest) -> dict[str, Any]:
    kind = request_body.kind.strip()
    if kind not in ("stories", "audiobook"):
        raise HTTPException(status_code=422, detail=f"Loại workspace không hợp lệ: {kind}")
    try:
        document = create_longform_document(
            kind=kind,
            source=request_body.source,
            payload=request_body.document,
            language=request_body.language,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    doc_id = uuid.uuid4().hex
    with _documents_lock:
        _documents[doc_id] = document
    return _document_dict(doc_id, kind, document)


@router.get("/document/{doc_id}")
def get_document(doc_id: str, kind: str = "stories") -> dict[str, Any]:
    with _documents_lock:
        document = _documents.get(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản nháp kế hoạch")
    return _document_dict(doc_id, kind, document)


class DocumentOpRequest(BaseModel):
    op: str
    item_id: str = ""
    after_id: str = ""
    chapter: str = ""
    name: str = ""
    changes: dict[str, Any] = {}
    position: int | None = None
    delta: int = 0
    second_id: str = ""
    document: dict[str, Any] = Field(default_factory=dict)


@router.post("/document/{doc_id}/ops")
def document_ops(doc_id: str, request_body: DocumentOpRequest, kind: str = "stories") -> dict[str, Any]:
    with _documents_lock:
        document = _documents.get(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản nháp kế hoạch")
    if request_body.document:
        try:
            document = EditableLongformDocument.from_payload(request_body.document)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        with _documents_lock:
            _documents[doc_id] = document
    op = request_body.op
    try:
        if op == "update":
            document.update(request_body.item_id, **request_body.changes)
        elif op == "add":
            document.add(after_id=request_body.after_id, chapter=request_body.chapter)
        elif op == "delete":
            document.delete(request_body.item_id)
        elif op == "move":
            document.move(request_body.item_id, int(request_body.delta))
        elif op == "split":
            document.split(request_body.item_id, request_body.position)
        elif op == "merge":
            document.merge(request_body.item_id, request_body.second_id)
        elif op == "add_chapter":
            document.add_chapter(request_body.name, after=request_body.chapter)
        elif op == "rename_chapter":
            document.rename_chapter(request_body.chapter, request_body.name)
        elif op == "move_chapter":
            document.move_chapter(request_body.chapter, request_body.delta)
        else:
            raise HTTPException(status_code=422, detail=f"Thao tác không hợp lệ: {op}")
    except (KeyError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return _document_dict(doc_id, kind, document)


def _document_dict(doc_id: str, kind: str, document: EditableLongformDocument) -> dict[str, Any]:
    plan = document.to_plan()
    return {
        "doc_id": doc_id,
        "kind": kind,
        "document": document.to_payload(),
        "script": document.to_script(kind),
        "voice_names": [name for name in plan.voice_names],
        "issues": [issue.__dict__ for issue in plan.issues],
    }


# ---------- Render (stories / audiobook / dubbing) ----------


def _parse_dubbing_segments(items: list[dict[str, Any]] | None) -> tuple[DubbingSegment, ...]:
    return tuple(
        DubbingSegment(
            segment_id=str(item.get("segment_id") or ""),
            start_ms=int(item.get("start_ms") or 0),
            end_ms=int(item.get("end_ms") or 0),
            source_text=str(item.get("source_text") or ""),
            text=str(item.get("text") or ""),
            speaker_id=str(item.get("speaker_id") or "Default"),
            profile_id=str(item.get("profile_id") or ""),
            speed=float(item.get("speed") or 1.0),
            volume=float(item.get("volume") or 1.0),
            preview_path=str(item.get("preview_path") or ""),
            source_speaker_id=str(item.get("source_speaker_id") or ""),
        )
        for item in items or ()
    )


def _dubbing_project_dict(project: DubbingProject) -> dict[str, Any]:
    return project.to_dict()


class DubbingProjectRequest(BaseModel):
    galaxy_project_id: str = ""
    project_id: str = ""
    expected_revision: int = 0
    name: str = "Dubbing"
    stage: str = "ingest"
    source_srt: str = ""
    translated_srt: str = ""
    source_video: str = ""
    source_audio: str = ""
    language: str = "vi"
    segments: list[dict[str, Any]] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    last_result: dict[str, Any] = Field(default_factory=dict)


@router.get("/dubbing/projects")
def list_dubbing_projects(
    request: Request,
    galaxy_project_id: str = "",
) -> list[dict[str, Any]]:
    return [
        item.__dict__
        for item in _dubbing_repository(request).list(galaxy_project_id=galaxy_project_id)
    ]


@router.get("/dubbing/projects/{project_id}")
def get_dubbing_project(project_id: str, request: Request) -> dict[str, Any]:
    project = _dubbing_repository(request).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy Dubbing project.")
    return _dubbing_project_dict(project)


@router.get("/dubbing/projects/{project_id}/media/{kind}")
def get_dubbing_project_media(project_id: str, kind: str, request: Request) -> FileResponse:
    project = _dubbing_repository(request).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy Dubbing project.")
    field = {"video": "video_path", "mixed": "mixed_audio_path", "voice": "wav_path"}.get(kind)
    if field is None:
        raise HTTPException(status_code=404, detail="Loại media không hợp lệ.")
    return _project_media_response(project.last_result, field)


def _project_media_response(last_result: Mapping[str, Any], field: str) -> FileResponse:
    root_value = str(last_result.get("project_dir") or "")
    path_value = str(last_result.get(field) or "")
    if not root_value or not path_value:
        raise HTTPException(status_code=404, detail="Project chưa có media này.")
    root = Path(root_value).expanduser().resolve()
    path = Path(path_value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=403, detail="Media nằm ngoài thư mục render.") from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File media không còn tồn tại.")
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        filename=None,
        content_disposition_type="inline",
    )


@router.post("/dubbing/projects")
def save_dubbing_project(body: DubbingProjectRequest, request: Request) -> dict[str, Any]:
    repository = _dubbing_repository(request)
    try:
        segments = _parse_dubbing_segments(body.segments)
        if body.project_id:
            existing = repository.get(body.project_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="Không tìm thấy Dubbing project.")
            project = existing.evolved(
                galaxy_project_id=body.galaxy_project_id.strip() or existing.galaxy_project_id,
                name=body.name.strip() or existing.name,
                stage=body.stage,
                source_srt=body.source_srt,
                translated_srt=body.translated_srt,
                source_video=body.source_video.strip(),
                source_audio=body.source_audio.strip(),
                language=body.language.strip() or "vi",
                segments=segments,
                options=body.options,
                quality=body.quality,
                # Render artifacts are server-owned because the media endpoint
                # trusts these paths after constraining them to project_dir.
                last_result=existing.last_result,
            )
        else:
            project = DubbingProject.create(
                galaxy_project_id=body.galaxy_project_id,
                name=body.name,
                source_srt=body.source_srt,
                translated_srt=body.translated_srt,
                source_video=body.source_video,
                source_audio=body.source_audio,
                language=body.language,
                segments=segments,
                options=body.options,
            )
            if body.stage != project.stage:
                project = project.evolved(stage=body.stage)
        saved = repository.save(project, expected_revision=body.expected_revision)
    except DubbingRevisionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    register_dubbing_project(_project_graph(request), saved)
    return _dubbing_project_dict(saved)


@router.delete("/dubbing/projects/{project_id}")
def delete_dubbing_project(project_id: str, request: Request) -> dict[str, bool]:
    _dubbing_repository(request).delete(project_id)
    return {"ok": True}


class DubbingPlanRequest(BaseModel):
    source_srt: str
    translated_srt: str = ""


@router.post("/dubbing/plan")
def create_dubbing_plan(body: DubbingPlanRequest) -> dict[str, Any]:
    try:
        source = parse_srt(body.source_srt)
        translated = parse_srt(body.translated_srt) if body.translated_srt.strip() else None
        if translated is not None and [cue.index for cue in source] != [cue.index for cue in translated]:
            raise ValueError("Sub gốc và bản dịch phải có cùng danh sách cue.")
        segments = build_dubbing_segments(source, translated)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _dubbing_plan_dict(segments)


class DubbingQualityRequest(BaseModel):
    segments: list[dict[str, Any]]
    min_tempo: float = 0.8
    max_tempo: float = 1.25
    tolerance_ms: int = 120
    min_gap_ms: int = 80
    max_chars_per_second: float = 22.0


@router.post("/dubbing/qc")
def dubbing_quality(body: DubbingQualityRequest) -> dict[str, Any]:
    try:
        segments = _parse_dubbing_segments(body.segments)
        policy = DubbingFitPolicy(
            min_tempo=max(0.5, min(1.0, body.min_tempo)),
            max_tempo=max(1.0, min(2.0, body.max_tempo)),
            tolerance_ms=max(0, body.tolerance_ms),
            min_gap_ms=max(0, body.min_gap_ms),
            max_chars_per_second=max(1.0, body.max_chars_per_second),
        )
        return build_dubbing_quality_report(segments, policy=policy).to_dict()
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class DubbingTranslateRequest(BaseModel):
    source_srt: str
    source_language: str = "auto"
    target_language: str = "vi"
    provider: str = ""
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    batch_size: int = 10
    max_workers: int = 2


@router.post("/dubbing/translate")
def translate_dubbing(body: DubbingTranslateRequest, request: Request) -> dict[str, Any]:
    try:
        source = parse_srt(body.source_srt)
        provider = normalize_translation_provider(body.provider)
        options = AITranslationOptions(
            source_language=body.source_language,
            target_language=body.target_language,
            provider=provider,
            model=body.model or default_translation_model(provider),
            base_url=body.base_url or default_translation_base_url(provider),
            api_key=body.api_key or default_translation_api_key(provider),
            batch_size=body.batch_size,
            max_workers=body.max_workers,
        )
        validate_translation_options(options)
    except (TypeError, ValueError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    # Re-running the request resumes from the deterministic translation checkpoint.
    # The in-memory task itself cannot be restored safely after an app restart.
    record = task_registry.create("dubbing-translate", resumable=False)
    checkpoint_path = translation_checkpoint_path(
        _settings_path(request).with_name("cache") / "dubbing",
        source,
        options,
    )

    def operation() -> dict[str, Any]:
        translated = translate_cues(
            source,
            options,
            checkpoint_path=checkpoint_path,
            progress=lambda done, total: _progress(record)(f"Da dich {done}/{total} cue..."),
            stop_event=record.stop_event,
        )
        segments = build_dubbing_segments(source, translated)
        return {
            "translated_srt": render_srt(translated),
            **_dubbing_plan_dict(segments),
        }

    run_task(record, operation, lambda result: result)
    return {"task_id": record.task_id}


def _dubbing_plan_dict(segments: tuple[DubbingSegment, ...]) -> dict[str, Any]:
    quality = build_dubbing_quality_report(segments)
    return {
        "segments": [item.__dict__ for item in segments],
        "issues": [item.__dict__ for item in quality.issues],
        "quality": quality.to_dict(),
    }


class RenderRequest(BaseModel):
    project_id: str = ""
    doc_id: str = ""
    kind: str = "stories"
    segments: list[dict[str, Any]] | None = None
    output_dir: str = ""
    project_name: str = "longform"
    mode: str = AUTO_MODE
    model_id: str = DEFAULT_MODEL_ID
    device: str = "auto"
    language: str = "vi"
    speed: float = 1.0
    cast_map: dict[str, str] = Field(default_factory=dict)
    gap_ms: int = 250
    export_mp3: bool = True
    export_m4b: bool = False
    export_stems: bool = False
    mastering: bool = False
    target_lufs: float = -16.0
    true_peak_db: float = -1.0
    preview_item_index: int | None = None
    title: str = ""
    author: str = ""
    cover_path: str = ""
    resume_project_dir: str = ""
    source_video: str = ""
    source_audio: str = ""
    mix_mode: str = "replace"
    source_volume: float = 0.25
    dub_volume: float = 1.0
    fit_min_tempo: float = 0.8
    fit_max_tempo: float = 1.25
    fit_tolerance_ms: int = 120
    min_gap_ms: int = 80


@router.post("/render")
def render(request_body: RenderRequest, request: Request) -> dict[str, Any]:
    runtime = _runtime()
    is_longform_preview = (
        request_body.kind != "dubbing" and request_body.preview_item_index is not None
    )
    longform_project: LongformProject | None = None
    if request_body.kind == "dubbing":
        if not request_body.segments:
            raise HTTPException(status_code=422, detail="Chưa có đoạn lồng tiếng.")
        try:
            segments = _parse_dubbing_segments(request_body.segments)
            issues = validate_dubbing_segments(segments)
            if any(issue.severity == "error" for issue in issues):
                raise HTTPException(
                    status_code=422,
                    detail="; ".join(issue.message for issue in issues if issue.severity == "error"),
                )
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=f"Đoạn lồng tiếng không hợp lệ: {error}")
    else:
        if request_body.project_id:
            longform_project = _longform_repository(request).get(request_body.project_id)
            if longform_project is None:
                raise HTTPException(status_code=404, detail="Không tìm thấy project Truyện & Sách nói.")
            if request_body.kind != longform_project.kind:
                raise HTTPException(status_code=422, detail="Loại render không khớp project Longform.")
            try:
                document = document_from_project(longform_project)
            except (TypeError, ValueError) as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        else:
            with _documents_lock:
                document = _documents.get(request_body.doc_id)
            if document is None:
                raise HTTPException(status_code=404, detail="Không tìm thấy bản nháp kế hoạch")
        plan = document.to_plan()
        if request_body.preview_item_index is not None:
            try:
                plan = preview_plan(plan, request_body.preview_item_index)
            except KeyError:
                raise HTTPException(status_code=404, detail="Không tìm thấy dòng cần nghe thử.")

    base_options = OmniVoiceGenerationOptions(
        mode=request_body.mode,
        text="",
        output_dir=(
            runtime.cache_dir / "longform_previews"
            if is_longform_preview
            else Path(request_body.output_dir or ".").expanduser()
        ),
        project_name=(
            f"preview-{request_body.project_name or 'longform'}"
            if is_longform_preview
            else request_body.project_name or "longform"
        ),
        model_id=request_body.model_id,
        device=request_body.device,
        language=request_body.language,
        speed=request_body.speed,
        export_mp3=False,
        profiles_dir=runtime.profiles_dir,
    )
    profiles = list_voice_profiles(runtime.profiles_dir)
    record = task_registry.create(
        "workspace-render",
        capability_id="tts.omnivoice",
        resumable=not is_longform_preview,
        resource_keys=resource_keys_for_device(request_body.device),
        project_id=request_body.project_id,
        workflow_id="dubbing" if request_body.kind == "dubbing" else request_body.kind,
    )
    record.on_cancel = lambda: _task_coordinator.cancel(record.task_id)
    resume_dir = (
        Path(request_body.resume_project_dir).expanduser() if request_body.resume_project_dir else None
    )
    def render_with_client(client):
        if request_body.kind == "dubbing":
            return render_dubbing_project(
                base_options,
                segments,
                client,
                profiles=profiles,
                cast_map=request_body.cast_map or None,
                fit_policy=DubbingFitPolicy(
                    min_tempo=max(0.5, min(1.0, request_body.fit_min_tempo)),
                    max_tempo=max(1.0, min(2.0, request_body.fit_max_tempo)),
                    tolerance_ms=max(0, request_body.fit_tolerance_ms),
                    min_gap_ms=max(0, request_body.min_gap_ms),
                ),
                export_mp3=request_body.export_mp3,
                export_stems=request_body.export_stems,
                source_video=Path(request_body.source_video).expanduser() if request_body.source_video else None,
                source_audio=Path(request_body.source_audio).expanduser() if request_body.source_audio else None,
                mix_mode=request_body.mix_mode,
                source_volume=request_body.source_volume,
                dub_volume=request_body.dub_volume,
                progress=_progress(record),
                resume_project_dir=resume_dir,
                stop_event=record.stop_event,
            )
        return render_longform_plan(
            base_options,
            plan,
            client,
            profiles=profiles,
            cast_map=request_body.cast_map or None,
            gap_ms=request_body.gap_ms,
            export_mp3=request_body.export_mp3,
            export_m4b=request_body.export_m4b,
            export_stems=request_body.export_stems,
            mastering=request_body.mastering,
            target_lufs=request_body.target_lufs,
            true_peak_db=request_body.true_peak_db,
            title=request_body.title,
            author=request_body.author,
            cover_path=Path(request_body.cover_path).expanduser() if request_body.cover_path else None,
            project_document=document.to_payload(),
            progress=_progress(record),
            resume_project_dir=resume_dir,
            stop_event=record.stop_event,
        )

    def serialize(result: Any) -> dict[str, Any]:
        payload = _render_result_dict(result)
        if request_body.kind == "dubbing" and request_body.project_id:
            repository = _dubbing_repository(request)
            project = repository.get(request_body.project_id)
            if project is not None:
                try:
                    quality = read_json(result.quality_report_path) if result.quality_report_path else {}
                    repository.save(
                        project.evolved(stage="export", quality=quality or {}, last_result=payload),
                        expected_revision=project.revision,
                    )
                except (DubbingRevisionConflict, ValueError):
                    pass
        elif longform_project is not None and request_body.preview_item_index is None:
            repository = _longform_repository(request)
            try:
                attach_longform_result(repository, longform_project.project_id, payload)
            except (LongformRevisionConflict, ValueError):
                pass
        return payload

    run_task(
        record,
        lambda: _task_coordinator.run(
            record.task_id,
            record.stop_event,
            render_with_client,
            client_factory=_worker_client,
        ),
        serialize,
    )
    return {"task_id": record.task_id}


@router.get("/resume-jobs")
def resume_jobs(output_dir: str) -> list[dict[str, Any]]:
    now = time.monotonic()
    key = str(output_dir)
    cached = _resume_cache["value"]
    if cached is None or cached.get("key") != key or now - _resume_cache["at"] > RESUME_CACHE_TTL_SECONDS:
        jobs = find_resumable_workspace_jobs(Path(output_dir).expanduser())
        _resume_cache["value"] = {
            "key": key,
            "jobs": [
                {
                    "project_dir": str(job.project_dir),
                    "project_name": job.project_name,
                    "total_spans": job.total_spans,
                    "completed_spans": job.completed_spans,
                    "status": job.status,
                    "error": job.error,
                    "updated_at": job.updated_at,
                }
                for job in jobs
            ],
        }
        _resume_cache["at"] = now
    return _resume_cache["value"]["jobs"]


@router.get("/dubbing/plan")
def dubbing_plan(srt_text: str) -> dict[str, Any]:
    try:
        cues = parse_srt(srt_text)
        segments = build_dubbing_segments(cues)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return _dubbing_plan_dict(segments)


def _render_result_dict(result: Any) -> dict[str, Any]:
    project_dir = Path(result.project_dir).resolve()

    def relative_file(path: Any) -> str | None:
        if not path:
            return None
        try:
            return str(Path(path).resolve().relative_to(project_dir)).replace("\\", "/")
        except ValueError:
            return None

    previews: list[str] = []
    for item in result.item_results:
        preview = relative_file(item.wav_path)
        if preview:
            previews.append(preview)
    quality = read_json(result.quality_report_path) if result.quality_report_path else None
    return {
        "project_dir": str(result.project_dir),
        "wav_path": str(result.wav_path),
        "srt_path": str(result.srt_path),
        "mp3_path": str(result.mp3_path) if result.mp3_path else None,
        "m4b_path": str(result.m4b_path) if result.m4b_path else None,
        "stems_dir": str(result.stems_dir) if result.stems_dir else None,
        "manifest_path": str(result.manifest_path),
        "span_count": len(result.item_results),
        "warnings": list(result.warnings),
        "quality_report_path": str(result.quality_report_path) if result.quality_report_path else None,
        "mixed_audio_path": str(result.mixed_audio_path) if result.mixed_audio_path else None,
        "video_path": str(result.video_path) if result.video_path else None,
        "fit_measurements": [item.__dict__ for item in result.fit_measurements],
        "quality": quality if isinstance(quality, dict) else None,
        "preview_files": previews,
        "wav_file": relative_file(result.wav_path),
        "mixed_audio_file": relative_file(result.mixed_audio_path),
        "video_file": relative_file(result.video_path),
    }
