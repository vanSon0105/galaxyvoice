"""Shared Voice project, history, and gallery endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...omnivoice.workspaces.common.repository import WorkspaceRepository
from ...omnivoice.workspaces.gallery import list_voice_archetypes, voice_archetype_categories
from ..event_bus import event_bus

router = APIRouter(prefix="/api/workspaces")

GALLERY_PAGE_SIZE = 120


def _settings_path(request: Request) -> Path:
    from ...common.config import default_config_path

    path = getattr(request.app.state, "settings_path", None)
    return Path(path) if path is not None else default_config_path()


def _repository(request: Request) -> WorkspaceRepository:
    return WorkspaceRepository(_settings_path(request).with_name("omnivoice_workspaces.json"))


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
