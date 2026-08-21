"""OmniVoice workspaces endpoints: repository, gallery, transcripts,
source imports, longform documents (stories/audiobook) and rendering.

The longform document lives in a server-side session and every edit op is
applied through the same EditableLongformDocument class the workspace service
uses, so the two UIs can never diverge on editing semantics.
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...common.errors import TaskCancelledError
from ...omnivoice.client import OmniVoiceWorkerClient
from ...omnivoice.models import AUTO_MODE, DEFAULT_MODEL_ID, OmniVoiceGenerationOptions
from ...omnivoice.profiles import list_voice_profiles
from ...omnivoice.runtime import OmniVoiceRuntime, load_supported_language_ids
from ...omnivoice.task_runner import shared_omnivoice_task_coordinator
from ...omnivoice.worker_pool import get_shared_worker_client
from ...omnivoice.workspaces.common.repository import WorkspaceRepository
from ...omnivoice.workspaces.dubbing.model import (
    DubbingSegment,
    build_dubbing_segments,
    plan_dubbing_segments,
    validate_dubbing_segments,
)
from ...omnivoice.workspaces.editable import EditableLongformDocument
from ...omnivoice.workspaces.gallery import list_voice_archetypes, voice_archetype_categories
from ...omnivoice.workspaces.imports import load_audiobook_source
from ...omnivoice.workspaces.renderer import (
    find_resumable_workspace_jobs,
    render_longform_plan,
)
from ...omnivoice.workspaces.transcripts import TranscriptStore
from ...voice.srt import parse_srt
from ..event_bus import event_bus
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


def _transcripts(request: Request) -> TranscriptStore:
    return TranscriptStore(_settings_path(request).with_name("transcriptions.json"))


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
    source: str


@router.post("/document")
def create_document(request_body: CreateDocumentRequest) -> dict[str, Any]:
    kind = request_body.kind.strip()
    if kind not in ("stories", "audiobook"):
        raise HTTPException(status_code=422, detail=f"Loại workspace không hợp lệ: {kind}")
    try:
        document = (
            EditableLongformDocument.from_story(request_body.source)
            if kind == "stories"
            else EditableLongformDocument.from_audiobook(request_body.source)
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
    changes: dict[str, Any] = {}
    position: int | None = None
    delta: int = 0
    second_id: str = ""


@router.post("/document/{doc_id}/ops")
def document_ops(doc_id: str, request_body: DocumentOpRequest, kind: str = "stories") -> dict[str, Any]:
    with _documents_lock:
        document = _documents.get(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản nháp kế hoạch")
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
        else:
            raise HTTPException(status_code=422, detail=f"Thao tác không hợp lệ: {op}")
    except (KeyError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return _document_dict(doc_id, kind, document)


def _document_dict(doc_id: str, kind: str, document: EditableLongformDocument) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "kind": kind,
        "document": document.to_payload(),
        "script": document.to_script(kind),
        "voice_names": [name for name in document.to_plan().voice_names],
    }


# ---------- Render (stories / audiobook / dubbing) ----------


class RenderRequest(BaseModel):
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
    cast_map: dict[str, str] = {}
    gap_ms: int = 250
    export_mp3: bool = True
    export_m4b: bool = False
    export_stems: bool = False
    title: str = ""
    author: str = ""
    cover_path: str = ""
    resume_project_dir: str = ""


@router.post("/render")
def render(request_body: RenderRequest) -> dict[str, Any]:
    runtime = _runtime()
    if request_body.kind == "dubbing":
        if not request_body.segments:
            raise HTTPException(status_code=422, detail="Chưa có đoạn lồng tiếng.")
        try:
            segments = tuple(
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
                )
                for item in request_body.segments
            )
            issues = validate_dubbing_segments(segments)
            if any(issue.severity == "error" for issue in issues):
                raise HTTPException(
                    status_code=422,
                    detail="; ".join(issue.message for issue in issues if issue.severity == "error"),
                )
            plan = plan_dubbing_segments(segments)
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=f"Đoạn lồng tiếng không hợp lệ: {error}")
    else:
        with _documents_lock:
            document = _documents.get(request_body.doc_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản nháp kế hoạch")
        plan = document.to_plan()

    base_options = OmniVoiceGenerationOptions(
        mode=request_body.mode,
        text="",
        output_dir=Path(request_body.output_dir or ".").expanduser(),
        project_name=request_body.project_name or "longform",
        model_id=request_body.model_id,
        device=request_body.device,
        language=request_body.language,
        speed=request_body.speed,
        export_mp3=False,
        profiles_dir=runtime.profiles_dir,
    )
    profiles = list_voice_profiles(runtime.profiles_dir)
    record = task_registry.create("workspace-render")
    record.on_cancel = lambda: _task_coordinator.cancel(record.task_id)
    resume_dir = (
        Path(request_body.resume_project_dir).expanduser() if request_body.resume_project_dir else None
    )
    run_task(
        record,
        lambda: _task_coordinator.run(
            record.task_id,
            record.stop_event,
            lambda client: render_longform_plan(
                base_options,
                plan,
                client,
                profiles=profiles,
                cast_map=request_body.cast_map or None,
                gap_ms=request_body.gap_ms,
                export_mp3=request_body.export_mp3,
                export_m4b=request_body.export_m4b,
                export_stems=request_body.export_stems,
                title=request_body.title,
                author=request_body.author,
                cover_path=Path(request_body.cover_path).expanduser() if request_body.cover_path else None,
                progress=_progress(record),
                resume_project_dir=resume_dir,
                stop_event=record.stop_event,
            ),
            client_factory=_worker_client,
        ),
        _render_result_dict,
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
    issues = validate_dubbing_segments(segments)
    return {
        "segments": [
            {
                "segment_id": segment.segment_id,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "source_text": segment.source_text,
                "text": segment.text,
                "speaker_id": segment.speaker_id,
                "profile_id": segment.profile_id,
                "speed": segment.speed,
                "volume": segment.volume,
            }
            for segment in segments
        ],
        "issues": [
            {"code": issue.code, "segment_id": issue.segment_id, "message": issue.message, "severity": issue.severity}
            for issue in issues
        ],
    }


def _render_result_dict(result: Any) -> dict[str, Any]:
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
    }
