from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from ....common.cache import read_json, write_json_atomic


_SECRET_KEYS = {
    "api_key",
    "apikey",
    "openai_api_key",
    "deepseek_api_key",
    "galaxy_translation_api_key",
    "authorization",
    "token",
    "access_token",
    "refresh_token",
}


@dataclass(frozen=True)
class WorkspaceProject:
    project_id: str
    workspace: str
    name: str
    payload: dict[str, object]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkspaceHistoryItem:
    history_id: str
    workspace: str
    title: str
    summary: str
    artifact_path: str
    metadata: dict[str, object]
    starred: bool
    created_at: str


class WorkspaceRepository:
    """Atomic local store for projects and generation history."""

    def __init__(self, path: Path, *, history_limit: int = 200) -> None:
        self.path = Path(path)
        self.history_limit = max(1, int(history_limit))
        self._lock = threading.RLock()

    def list_projects(self, workspace: str = "") -> tuple[WorkspaceProject, ...]:
        projects, _history = self._load()
        selected = (
            projects
            if not workspace.strip()
            else tuple(item for item in projects if item.workspace == workspace.strip())
        )
        return tuple(sorted(selected, key=lambda item: item.updated_at, reverse=True))

    def get_project(self, project_id: str) -> WorkspaceProject | None:
        return next(
            (item for item in self.list_projects() if item.project_id == project_id),
            None,
        )

    def save_project(
        self,
        *,
        workspace: str,
        name: str,
        payload: Mapping[str, object],
        project_id: str = "",
    ) -> WorkspaceProject:
        workspace_name = workspace.strip()
        display_name = name.strip()
        if not workspace_name or not display_name:
            raise ValueError("Workspace và tên project không được để trống.")
        with self._lock:
            projects, history = self._load()
            existing = next(
                (item for item in projects if item.project_id == project_id),
                None,
            )
            now = _now()
            project = WorkspaceProject(
                project_id=existing.project_id if existing else uuid4().hex,
                workspace=workspace_name,
                name=display_name,
                payload=_sanitize_mapping(payload),
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            updated = tuple(
                project if item.project_id == project.project_id else item for item in projects
            )
            if existing is None:
                updated = (project, *updated)
            self._save(updated, history)
            return project

    def delete_project(self, project_id: str) -> None:
        with self._lock:
            projects, history = self._load()
            self._save(
                tuple(item for item in projects if item.project_id != project_id),
                history,
            )

    def list_history(self, workspace: str = "") -> tuple[WorkspaceHistoryItem, ...]:
        _projects, history = self._load()
        if workspace.strip():
            history = tuple(item for item in history if item.workspace == workspace.strip())
        return tuple(sorted(history, key=lambda item: item.created_at, reverse=True))

    def search_history(
        self,
        query: str,
        *,
        workspace: str = "",
        starred_only: bool = False,
    ) -> tuple[WorkspaceHistoryItem, ...]:
        needle = query.strip().casefold()
        return tuple(
            item
            for item in self.list_history(workspace)
            if (not starred_only or item.starred)
            and (
                not needle
                or needle
                in f"{item.title} {item.summary} {item.artifact_path}".casefold()
            )
        )

    def add_history(
        self,
        *,
        workspace: str,
        title: str,
        summary: str,
        artifact_path: str,
        metadata: Mapping[str, object] | None = None,
    ) -> WorkspaceHistoryItem:
        if not workspace.strip() or not title.strip():
            raise ValueError("Workspace và tiêu đề history không được để trống.")
        item = WorkspaceHistoryItem(
            history_id=uuid4().hex,
            workspace=workspace.strip(),
            title=title.strip(),
            summary=summary.strip(),
            artifact_path=artifact_path.strip(),
            metadata=_sanitize_mapping(metadata or {}),
            starred=False,
            created_at=_now(),
        )
        with self._lock:
            projects, history = self._load()
            self._save(projects, self._trim_history((item, *history)))
        return item

    def set_history_starred(
        self,
        history_id: str,
        starred: bool,
    ) -> WorkspaceHistoryItem:
        with self._lock:
            projects, history = self._load()
            target = next(
                (item for item in history if item.history_id == history_id),
                None,
            )
            if target is None:
                raise KeyError(history_id)
            replacement = WorkspaceHistoryItem(**{**asdict(target), "starred": bool(starred)})
            updated = tuple(
                replacement if item.history_id == history_id else item for item in history
            )
            self._save(projects, self._trim_history(updated))
            return replacement

    def delete_history(self, history_id: str) -> None:
        with self._lock:
            projects, history = self._load()
            self._save(
                projects,
                tuple(item for item in history if item.history_id != history_id),
            )

    def clear_history(self, workspace: str = "") -> None:
        with self._lock:
            projects, history = self._load()
            kept = (
                tuple(item for item in history if item.workspace != workspace.strip())
                if workspace.strip()
                else ()
            )
            self._save(projects, kept)

    def _trim_history(
        self,
        history: tuple[WorkspaceHistoryItem, ...],
    ) -> tuple[WorkspaceHistoryItem, ...]:
        ordered = tuple(sorted(history, key=lambda item: item.created_at, reverse=True))
        starred = [item for item in ordered if item.starred]
        ordinary = [item for item in ordered if not item.starred]
        return tuple((starred + ordinary)[: self.history_limit])

    def _load(self) -> tuple[tuple[WorkspaceProject, ...], tuple[WorkspaceHistoryItem, ...]]:
        payload = read_json(self.path)
        if not isinstance(payload, dict):
            return (), ()
        return (
            tuple(_read_project(item) for item in payload.get("projects", []) if isinstance(item, dict)),
            tuple(_read_history(item) for item in payload.get("history", []) if isinstance(item, dict)),
        )

    def _save(
        self,
        projects: tuple[WorkspaceProject, ...],
        history: tuple[WorkspaceHistoryItem, ...],
    ) -> None:
        write_json_atomic(
            self.path,
            {
                "version": 1,
                "projects": [asdict(item) for item in projects],
                "history": [asdict(item) for item in history],
            },
        )


def _read_project(payload: dict[str, object]) -> WorkspaceProject:
    return WorkspaceProject(
        project_id=str(payload.get("project_id") or ""),
        workspace=str(payload.get("workspace") or ""),
        name=str(payload.get("name") or ""),
        payload=_sanitize_mapping(payload.get("payload") if isinstance(payload.get("payload"), dict) else {}),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
    )


def _read_history(payload: dict[str, object]) -> WorkspaceHistoryItem:
    return WorkspaceHistoryItem(
        history_id=str(payload.get("history_id") or ""),
        workspace=str(payload.get("workspace") or ""),
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or ""),
        artifact_path=str(payload.get("artifact_path") or ""),
        metadata=_sanitize_mapping(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
        starred=bool(payload.get("starred")),
        created_at=str(payload.get("created_at") or ""),
    )


def _sanitize_mapping(payload: Mapping[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for raw_key, value in payload.items():
        key = str(raw_key)
        if key.casefold() in _SECRET_KEYS or key.casefold().endswith("_api_key"):
            continue
        if isinstance(value, Mapping):
            cleaned[key] = _sanitize_mapping(value)
        elif isinstance(value, (list, tuple)):
            cleaned[key] = [
                _sanitize_mapping(item) if isinstance(item, Mapping) else item
                for item in value
            ]
        elif value is None or isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
