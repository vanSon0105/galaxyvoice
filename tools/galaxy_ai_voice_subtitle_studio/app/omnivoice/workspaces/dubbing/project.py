from __future__ import annotations

import shutil
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from ....common.cache import read_json, write_json_atomic
from .model import DubbingSegment


DUBBING_STAGES = (
    "ingest",
    "translation",
    "cast",
    "synthesis",
    "fit",
    "qc",
    "export",
)


class DubbingRevisionConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class DubbingProjectSummary:
    project_id: str
    name: str
    stage: str
    revision: int
    segment_count: int
    language: str
    updated_at: str


@dataclass(frozen=True)
class DubbingProject:
    project_id: str
    name: str
    stage: str
    revision: int
    source_srt: str
    translated_srt: str
    source_video: str
    source_audio: str
    language: str
    segments: tuple[DubbingSegment, ...]
    options: Mapping[str, Any] = field(default_factory=dict)
    quality: Mapping[str, Any] = field(default_factory=dict)
    last_result: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        name: str,
        source_srt: str,
        segments: tuple[DubbingSegment, ...],
        translated_srt: str = "",
        source_video: str = "",
        source_audio: str = "",
        language: str = "vi",
        options: Mapping[str, Any] | None = None,
    ) -> "DubbingProject":
        now = _now()
        return cls(
            project_id=uuid4().hex,
            name=name.strip() or "Dubbing",
            stage="translation" if translated_srt.strip() else "ingest",
            revision=1,
            source_srt=source_srt,
            translated_srt=translated_srt,
            source_video=source_video.strip(),
            source_audio=source_audio.strip(),
            language=language.strip() or "vi",
            segments=segments,
            options=_sanitize(options or {}),
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DubbingProject":
        return cls(
            project_id=str(payload.get("project_id") or ""),
            name=str(payload.get("name") or "Dubbing"),
            stage=_stage(str(payload.get("stage") or "ingest")),
            revision=max(1, int(payload.get("revision") or 1)),
            source_srt=str(payload.get("source_srt") or ""),
            translated_srt=str(payload.get("translated_srt") or ""),
            source_video=str(payload.get("source_video") or ""),
            source_audio=str(payload.get("source_audio") or ""),
            language=str(payload.get("language") or "vi"),
            segments=tuple(
                DubbingSegment(**item)
                for item in payload.get("segments", ())
                if isinstance(item, Mapping)
            ),
            options=_sanitize(payload.get("options") or {}),
            quality=_sanitize(payload.get("quality") or {}),
            last_result=_sanitize(payload.get("last_result") or {}),
            created_at=str(payload.get("created_at") or _now()),
            updated_at=str(payload.get("updated_at") or _now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "project_id": self.project_id,
            "name": self.name,
            "stage": self.stage,
            "revision": self.revision,
            "source_srt": self.source_srt,
            "translated_srt": self.translated_srt,
            "source_video": self.source_video,
            "source_audio": self.source_audio,
            "language": self.language,
            "segments": [asdict(item) for item in self.segments],
            "options": _sanitize(self.options),
            "quality": _sanitize(self.quality),
            "last_result": _sanitize(self.last_result),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def evolved(self, **changes: Any) -> "DubbingProject":
        if "stage" in changes:
            changes["stage"] = _stage(str(changes["stage"]))
        return replace(self, revision=self.revision + 1, updated_at=_now(), **changes)

    def summary(self) -> DubbingProjectSummary:
        return DubbingProjectSummary(
            project_id=self.project_id,
            name=self.name,
            stage=self.stage,
            revision=self.revision,
            segment_count=len(self.segments),
            language=self.language,
            updated_at=self.updated_at,
        )


class DubbingProjectRepository:
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, index_path: Path) -> None:
        self.index_path = Path(index_path)
        self.documents_dir = self.index_path.with_suffix("") / "_documents"
        key = str(self.index_path.resolve())
        with self._locks_guard:
            self._lock = self._locks.setdefault(key, threading.RLock())

    def list(self) -> tuple[DubbingProjectSummary, ...]:
        with self._lock:
            payload = read_json(self.index_path)
        items = payload.get("projects", ()) if isinstance(payload, dict) else ()
        summaries = tuple(
            DubbingProjectSummary(
                project_id=str(item.get("project_id") or ""),
                name=str(item.get("name") or "Dubbing"),
                stage=_stage(str(item.get("stage") or "ingest")),
                revision=max(1, int(item.get("revision") or 1)),
                segment_count=max(0, int(item.get("segment_count") or 0)),
                language=str(item.get("language") or "vi"),
                updated_at=str(item.get("updated_at") or ""),
            )
            for item in items
            if isinstance(item, Mapping) and item.get("project_id")
        )
        return tuple(sorted(summaries, key=lambda item: item.updated_at, reverse=True))

    def get(self, project_id: str) -> DubbingProject | None:
        payload = read_json(self._document_path(project_id))
        return DubbingProject.from_dict(payload) if isinstance(payload, dict) else None

    def save(self, project: DubbingProject, *, expected_revision: int) -> DubbingProject:
        with self._lock:
            existing = self.get(project.project_id)
            current_revision = existing.revision if existing is not None else 0
            if current_revision != max(0, int(expected_revision)):
                raise DubbingRevisionConflict(
                    f"Dubbing project đã thay đổi (server {current_revision}, client {expected_revision})."
                )
            saved = project
            if existing is None:
                saved = replace(project, revision=1, created_at=project.created_at or _now(), updated_at=_now())
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
            artifact_dir = self.index_path.with_suffix("") / "artifacts" / project_id
            if artifact_dir.is_dir():
                shutil.rmtree(artifact_dir)

    def _document_path(self, project_id: str) -> Path:
        safe = "".join(character for character in project_id if character.isalnum() or character in "-_")
        if not safe or safe != project_id:
            raise ValueError("Dubbing project ID không hợp lệ.")
        return self.documents_dir / f"{safe}.json"


def _stage(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in DUBBING_STAGES:
        raise ValueError(f"Dubbing stage không hợp lệ: {value}")
    return normalized


def _sanitize(payload: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for raw_key, value in payload.items():
        key = str(raw_key)
        if "api_key" in key.casefold() or "token" in key.casefold() or "secret" in key.casefold():
            continue
        if isinstance(value, Mapping):
            cleaned[key] = _sanitize(value)
        elif isinstance(value, (list, tuple)):
            cleaned[key] = [_sanitize(item) if isinstance(item, Mapping) else item for item in value]
        elif value is None or isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
    return cleaned


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
