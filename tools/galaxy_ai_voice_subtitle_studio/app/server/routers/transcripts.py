from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from ...common.config import default_config_path
from ...project_graph.integrations import register_transcript_handoff
from ...project_graph.runtime import project_graph_service
from ...project_graph.service import ProjectGraphService
from ...runtime.jobs import TaskContext
from ...runtime.resources import resource_keys_for_device
from ...transcripts.models import TranscriptProject
from ...transcripts.repository import RevisionConflictError, TranscriptRepository
from ...transcripts.service import TranscriptService
from ..event_bus import event_bus
from ..tasks import task_registry

router = APIRouter(prefix="/api/transcripts", tags=["transcripts"])


def _settings_path(request: Request) -> Path:
    path = getattr(request.app.state, "settings_path", None)
    return Path(path) if path is not None else default_config_path()


def _repository(request: Request) -> TranscriptRepository:
    return TranscriptRepository(_settings_path(request).with_name("transcript_projects.json"))


def _service(request: Request) -> TranscriptService:
    return TranscriptService(_repository(request))


def _graph_service(request: Request) -> ProjectGraphService:
    return project_graph_service(_settings_path(request))


class ImportMediaRequest(BaseModel):
    project_id: str = Field(min_length=1)
    media_path: str
    name: str = ""
    language: str = "auto"
    model_size: str = "base"
    device: str = "auto"
    diarization: bool = False


class ImportTextRequest(BaseModel):
    project_id: str = Field(min_length=1)
    name: str = "Transcript"
    content: str
    format_type: str = "srt"
    language: str = "vi"
    source_path: str = ""


class EditCueRequest(BaseModel):
    text: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    speaker_id: str | None = None
    expected_revision: int | None = None


class SplitCueRequest(BaseModel):
    split_ms: int
    first_text: str
    second_text: str
    expected_revision: int | None = None


class MergeCuesRequest(BaseModel):
    first_cue_id: str
    second_cue_id: str
    separator: str = " "
    expected_revision: int | None = None


class SpeakerRequest(BaseModel):
    label: str
    color: str = "#d08ca1"
    expected_revision: int | None = None


class SaveDocumentRequest(BaseModel):
    cues: list[dict[str, Any]]
    speakers: list[dict[str, Any]]
    expected_revision: int = Field(ge=1)


@router.get("/projects")
def list_projects(
    request: Request,
    project_id: str = "",
    query: str = "",
) -> list[dict[str, Any]]:
    if not project_id.strip():
        return []
    items = _repository(request).list(project_id=project_id, query=query)
    return [item.to_dict(include_cues=False) for item in items]


@router.get("/projects/{transcript_id}")
def get_project(transcript_id: str, request: Request) -> dict[str, Any]:
    item = _repository(request).get(transcript_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy transcript.")
    return item.to_dict(include_cues=True)


@router.delete("/projects/{transcript_id}")
def delete_project(transcript_id: str, request: Request) -> dict[str, bool]:
    ok = _repository(request).delete(transcript_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Không tìm thấy transcript để xóa.")
    event_bus.emit({"type": "event", "kind": "transcripts_updated", "payload": {"transcript_id": transcript_id}})
    return {"ok": True}


@router.post("/import-text")
def import_text(body: ImportTextRequest, request: Request) -> dict[str, Any]:
    try:
        project = _service(request).import_text(
            project_id=body.project_id,
            name=body.name,
            content=body.content,
            format_type=body.format_type,
            language=body.language,
            source_path=body.source_path,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    event_bus.emit({"type": "event", "kind": "transcripts_updated", "payload": {"transcript_id": project.transcript_id}})
    return project.to_dict(include_cues=True)


@router.post("/import-media")
def import_media(body: ImportMediaRequest, request: Request) -> dict[str, str]:
    media = Path(body.media_path).expanduser().resolve()
    if not media.is_file():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy file media: {media}")

    record = task_registry.create(
        "transcript-asr",
        capability_id="asr.faster-whisper",
        project_id=body.project_id,
        resource_keys=resource_keys_for_device(body.device),
    )

    def operation(context: TaskContext) -> TranscriptProject:
        project = _service(request).import_media(
            project_id=body.project_id,
            media_path=media,
            name=body.name,
            language=body.language,
            model_size=body.model_size,
            device=body.device,
            diarization=body.diarization,
            progress=lambda msg: context.report(msg),
            stop_event=record.stop_event,
        )
        return project

    task_registry.submit(record, operation, lambda project: project.to_dict(include_cues=False))
    event_bus.emit(
        {"type": "event", "kind": "transcript_asr_started", "payload": {"task_id": record.task_id}}
    )
    return {"task_id": record.task_id}


@router.patch("/projects/{transcript_id}/cues/{cue_id}")
def edit_cue(
    transcript_id: str,
    cue_id: str,
    body: EditCueRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        project = _service(request).edit_cue(
            transcript_id,
            cue_id,
            text=body.text,
            start_ms=body.start_ms,
            end_ms=body.end_ms,
            speaker_id=body.speaker_id,
            expected_revision=body.expected_revision,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RevisionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    event_bus.emit({"type": "event", "kind": "transcripts_updated", "payload": {"transcript_id": transcript_id}})
    return project.to_dict(include_cues=True)


@router.put("/projects/{transcript_id}/document")
def save_document(
    transcript_id: str,
    body: SaveDocumentRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        project = _service(request).replace_document(
            transcript_id,
            cues=body.cues,
            speakers=body.speakers,
            expected_revision=body.expected_revision,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RevisionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    event_bus.emit(
        {"type": "event", "kind": "transcripts_updated", "payload": {"transcript_id": transcript_id}}
    )
    return project.to_dict(include_cues=True)


@router.post("/projects/{transcript_id}/cues/{cue_id}/split")
def split_cue(
    transcript_id: str,
    cue_id: str,
    body: SplitCueRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        project = _service(request).split_cue(
            transcript_id,
            cue_id,
            split_ms=body.split_ms,
            first_text=body.first_text,
            second_text=body.second_text,
            expected_revision=body.expected_revision,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RevisionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    event_bus.emit({"type": "event", "kind": "transcripts_updated", "payload": {"transcript_id": transcript_id}})
    return project.to_dict(include_cues=True)


@router.post("/projects/{transcript_id}/merge-cues")
def merge_cues(
    transcript_id: str,
    body: MergeCuesRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        project = _service(request).merge_cues(
            transcript_id,
            first_cue_id=body.first_cue_id,
            second_cue_id=body.second_cue_id,
            separator=body.separator,
            expected_revision=body.expected_revision,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RevisionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    event_bus.emit({"type": "event", "kind": "transcripts_updated", "payload": {"transcript_id": transcript_id}})
    return project.to_dict(include_cues=True)


@router.delete("/projects/{transcript_id}/cues/{cue_id}")
def delete_cue(
    transcript_id: str,
    cue_id: str,
    request: Request,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    try:
        project = _service(request).delete_cue(
            transcript_id,
            cue_id,
            expected_revision=expected_revision,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RevisionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    event_bus.emit({"type": "event", "kind": "transcripts_updated", "payload": {"transcript_id": transcript_id}})
    return project.to_dict(include_cues=True)


@router.post("/projects/{transcript_id}/speakers")
def add_speaker(
    transcript_id: str,
    body: SpeakerRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        project = _service(request).add_speaker(
            transcript_id,
            label=body.label,
            color=body.color,
            expected_revision=body.expected_revision,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RevisionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    event_bus.emit({"type": "event", "kind": "transcripts_updated", "payload": {"transcript_id": transcript_id}})
    return project.to_dict(include_cues=True)


@router.patch("/projects/{transcript_id}/speakers/{speaker_id}")
def update_speaker(
    transcript_id: str,
    speaker_id: str,
    body: SpeakerRequest,
    request: Request,
) -> dict[str, Any]:
    try:
        project = _service(request).update_speaker(
            transcript_id,
            speaker_id=speaker_id,
            label=body.label,
            color=body.color,
            expected_revision=body.expected_revision,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RevisionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    event_bus.emit({"type": "event", "kind": "transcripts_updated", "payload": {"transcript_id": transcript_id}})
    return project.to_dict(include_cues=True)


@router.get("/projects/{transcript_id}/export")
def export_file(
    transcript_id: str,
    request: Request,
    format: str = "srt",
) -> PlainTextResponse:
    normalized_format = format.strip().casefold()
    if normalized_format not in {"srt", "vtt", "txt"}:
        raise HTTPException(status_code=422, detail="Định dạng xuất phải là SRT, VTT hoặc TXT.")
    try:
        project = _repository(request).get(transcript_id)
        if project is None:
            raise KeyError(transcript_id)
        content = _service(request).export_text(transcript_id, format_type=normalized_format)
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy transcript.")
    media_type = "text/vtt" if normalized_format == "vtt" else "text/plain"
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", project.name).strip("-.") or "transcript"
    encoded_name = quote(f"{project.name}.{normalized_format}", safe="")
    return PlainTextResponse(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{safe_name}.{normalized_format}"; '
                f"filename*=UTF-8''{encoded_name}"
            )
        },
    )


@router.get("/projects/{transcript_id}/media")
def source_media(transcript_id: str, request: Request) -> FileResponse:
    project = _repository(request).get(transcript_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy transcript.")
    path = Path(project.source_path)
    if project.source_kind not in {"audio", "video"} or not path.is_file():
        raise HTTPException(status_code=404, detail="Media nguồn không còn tồn tại.")
    return FileResponse(path, filename=None, content_disposition_type="inline")


@router.get("/projects/{transcript_id}/speakers/{speaker_id}/reference")
def speaker_reference(
    transcript_id: str,
    speaker_id: str,
    request: Request,
) -> FileResponse:
    project = _repository(request).get(transcript_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy transcript.")
    speaker = next((item for item in project.speakers if item.speaker_id == speaker_id), None)
    if speaker is None or not speaker.reference_path:
        raise HTTPException(status_code=404, detail="Người nói chưa có audio mẫu.")
    path = Path(speaker.reference_path)
    allowed_root = _repository(request).project_dir(transcript_id).resolve()
    try:
        path.resolve().relative_to(allowed_root)
    except ValueError as error:
        raise HTTPException(status_code=403, detail="Đường dẫn audio mẫu không hợp lệ.") from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio mẫu không còn tồn tại.")
    return FileResponse(path, media_type="audio/wav", filename=None, content_disposition_type="inline")


@router.post("/projects/{transcript_id}/handoffs/{target}")
def create_handoff(transcript_id: str, target: str, request: Request) -> dict[str, Any]:
    try:
        project, payload = _service(request).record_handoff(transcript_id, target)
        register_transcript_handoff(_graph_service(request), project, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy transcript.")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    event_bus.emit(
        {"type": "event", "kind": "transcript_handoff_created", "payload": payload}
    )
    return payload


@router.get("/projects/{transcript_id}/handoffs/{target}")
def get_handoff(transcript_id: str, target: str, request: Request) -> dict[str, Any]:
    try:
        return _service(request).get_handoff(transcript_id, target)
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy handoff transcript.")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/projects/{transcript_id}/dubbing-handoff")
def legacy_dubbing_handoff(transcript_id: str, request: Request) -> list[dict[str, Any]]:
    """Compatibility endpoint for clients shipped before native handoff records."""
    try:
        return _service(request).export_dubbing_handoff(transcript_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Không tìm thấy transcript.")
