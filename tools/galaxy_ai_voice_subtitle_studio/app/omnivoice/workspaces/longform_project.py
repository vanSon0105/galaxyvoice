from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from ...common.cache import read_json, write_json_atomic


LONGFORM_KINDS = frozenset({"stories", "audiobook"})
LONGFORM_STAGES = frozenset({"source", "plan", "cast", "render", "export"})


class LongformRevisionConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class LongformProjectSummary:
    project_id: str
    name: str
    kind: str
    stage: str
    revision: int
    item_count: int
    chapter_count: int
    updated_at: str


@dataclass(frozen=True)
class LongformProject:
    project_id: str
    name: str
    kind: str
    stage: str
    revision: int
    source: str
    document: Mapping[str, Any]
    language: str = "vi"
    options: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    last_result: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        name: str,
        kind: str,
        source: str,
        document: Mapping[str, Any],
        language: str = "vi",
        options: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LongformProject":
        now = _now()
        return cls(
            project_id=uuid4().hex,
            name=name.strip() or "longform",
            kind=_kind(kind),
            stage="plan" if _item_count(document) else "source",
            revision=1,
            source=source,
            document=_sanitize(document),
            language=language.strip() or "vi",
            options=_sanitize(options or {}),
            metadata=_sanitize(metadata or {}),
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LongformProject":
        return cls(
            project_id=str(payload.get("project_id") or ""),
            name=str(payload.get("name") or "longform"),
            kind=_kind(str(payload.get("kind") or "stories")),
            stage=_stage(str(payload.get("stage") or "source")),
            revision=max(1, int(payload.get("revision") or 1)),
            source=str(payload.get("source") or ""),
            document=_sanitize(payload.get("document") or {}),
            language=str(payload.get("language") or "vi"),
            options=_sanitize(payload.get("options") or {}),
            metadata=_sanitize(payload.get("metadata") or {}),
            last_result=_sanitize(payload.get("last_result") or {}),
            created_at=str(payload.get("created_at") or _now()),
            updated_at=str(payload.get("updated_at") or _now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "project_id": self.project_id,
            "name": self.name,
            "kind": self.kind,
            "stage": self.stage,
            "revision": self.revision,
            "source": self.source,
            "document": _sanitize(self.document),
            "language": self.language,
            "options": _sanitize(self.options),
            "metadata": _sanitize(self.metadata),
            "last_result": _sanitize(self.last_result),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def evolved(self, **changes: Any) -> "LongformProject":
        if "kind" in changes:
            changes["kind"] = _kind(str(changes["kind"]))
        if "stage" in changes:
            changes["stage"] = _stage(str(changes["stage"]))
        for field_name in ("document", "options", "metadata", "last_result"):
            if field_name in changes:
                changes[field_name] = _sanitize(changes[field_name])
        return replace(self, revision=self.revision + 1, updated_at=_now(), **changes)

    def summary(self) -> LongformProjectSummary:
        chapters = self.document.get("chapters")
        return LongformProjectSummary(
            project_id=self.project_id,
            name=self.name,
            kind=self.kind,
            stage=self.stage,
            revision=self.revision,
            item_count=_item_count(self.document),
            chapter_count=len(chapters) if isinstance(chapters, list) else 0,
            updated_at=self.updated_at,
        )


class LongformProjectRepository:
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, index_path: Path) -> None:
        self.index_path = Path(index_path)
        self.documents_dir = self.index_path.with_suffix("") / "_documents"
        key = str(self.index_path.resolve())
        with self._locks_guard:
            self._lock = self._locks.setdefault(key, threading.RLock())

    def list(self, kind: str = "") -> tuple[LongformProjectSummary, ...]:
        with self._lock:
            payload = read_json(self.index_path)
        items = payload.get("projects", ()) if isinstance(payload, dict) else ()
        summaries = tuple(
            LongformProjectSummary(
                project_id=str(item.get("project_id") or ""),
                name=str(item.get("name") or "longform"),
                kind=_kind(str(item.get("kind") or "stories")),
                stage=_stage(str(item.get("stage") or "source")),
                revision=max(1, int(item.get("revision") or 1)),
                item_count=max(0, int(item.get("item_count") or 0)),
                chapter_count=max(0, int(item.get("chapter_count") or 0)),
                updated_at=str(item.get("updated_at") or ""),
            )
            for item in items
            if isinstance(item, Mapping) and item.get("project_id")
        )
        normalized_kind = kind.strip().lower()
        filtered = summaries if not normalized_kind else tuple(
            item for item in summaries if item.kind == normalized_kind
        )
        return tuple(sorted(filtered, key=lambda item: item.updated_at, reverse=True))

    def get(self, project_id: str) -> LongformProject | None:
        payload = read_json(self._document_path(project_id))
        return LongformProject.from_dict(payload) if isinstance(payload, dict) else None

    def save(self, project: LongformProject, *, expected_revision: int) -> LongformProject:
        with self._lock:
            existing = self.get(project.project_id)
            current_revision = existing.revision if existing else 0
            if current_revision != max(0, int(expected_revision)):
                raise LongformRevisionConflict(
                    f"Project đã thay đổi (server {current_revision}, client {expected_revision})."
                )
            saved = project
            if existing is None:
                saved = replace(
                    project,
                    revision=1,
                    created_at=project.created_at or _now(),
                    updated_at=_now(),
                )
            elif project.revision != existing.revision + 1:
                saved = replace(project, revision=existing.revision + 1, updated_at=_now())
            write_json_atomic(self._document_path(saved.project_id), saved.to_dict())
            summaries = [item for item in self.list() if item.project_id != saved.project_id]
            summaries.insert(0, saved.summary())
            write_json_atomic(
                self.index_path,
                {"schema_version": 1, "projects": [asdict(item) for item in summaries]},
            )
            return saved

    def delete(self, project_id: str) -> None:
        with self._lock:
            self._document_path(project_id).unlink(missing_ok=True)
            summaries = [item for item in self.list() if item.project_id != project_id]
            write_json_atomic(
                self.index_path,
                {"schema_version": 1, "projects": [asdict(item) for item in summaries]},
            )

    def _document_path(self, project_id: str) -> Path:
        safe = "".join(character for character in project_id if character.isalnum() or character in "-_")
        if not safe or safe != project_id:
            raise ValueError("Longform project ID không hợp lệ.")
        return self.documents_dir / f"{safe}.json"


def _item_count(document: Mapping[str, Any]) -> int:
    items = document.get("items")
    return len(items) if isinstance(items, list) else 0


def _kind(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in LONGFORM_KINDS:
        raise ValueError(f"Loại Longform không hợp lệ: {value}")
    return normalized


def _stage(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in LONGFORM_STAGES:
        raise ValueError(f"Giai đoạn Longform không hợp lệ: {value}")
    return normalized


def _sanitize(payload: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for raw_key, value in payload.items():
        key = str(raw_key)
        normalized = key.casefold()
        if "api_key" in normalized or "token" in normalized or "secret" in normalized:
            continue
        if isinstance(value, Mapping):
            cleaned[key] = _sanitize(value)
        elif isinstance(value, (list, tuple)):
            cleaned[key] = [
                _sanitize(item) if isinstance(item, Mapping) else item
                for item in value
                if item is None or isinstance(item, (Mapping, str, int, float, bool))
            ]
        elif value is None or isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
    return cleaned


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
