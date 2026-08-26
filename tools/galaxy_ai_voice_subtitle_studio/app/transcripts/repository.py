from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Callable

from ..common.cache import read_json, write_json_atomic
from .models import TranscriptProject, validate_project


class RevisionConflictError(RuntimeError):
    pass


class TranscriptRepository:
    """Atomic indexed store with one document per transcript."""

    _locks_guard = threading.Lock()
    _locks: dict[Path, threading.RLock] = {}

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.artifacts_dir = self.path.with_suffix("")
        self.documents_dir = self.artifacts_dir / "_documents"
        with self._locks_guard:
            self._lock = self._locks.setdefault(self.path, threading.RLock())

    def list(self, *, project_id: str = "", query: str = "") -> tuple[TranscriptProject, ...]:
        needle = query.strip().casefold()
        with self._lock:
            items = self._load_index_unlocked()
            if project_id:
                items = tuple(item for item in items if item.project_id == project_id)
            if needle:
                detailed = tuple(self._get_unlocked(item.transcript_id) or item for item in items)
                items = tuple(
                    item for item in detailed if needle in self._search_text(item).casefold()
                )
            return tuple(sorted(items, key=lambda item: item.updated_at, reverse=True))

    def get(self, transcript_id: str) -> TranscriptProject | None:
        with self._lock:
            return self._get_unlocked(transcript_id)

    def create(self, project: TranscriptProject) -> TranscriptProject:
        validate_project(project)
        with self._lock:
            items = self._load_index_unlocked()
            if any(item.transcript_id == project.transcript_id for item in items):
                raise ValueError("Transcript đã tồn tại.")
            self._migrate_legacy_documents_unlocked(items)
            self._write_document_unlocked(project)
            self._save_index_unlocked((project, *items))
        return project

    def replace(
        self,
        project: TranscriptProject,
        *,
        expected_revision: int | None = None,
    ) -> TranscriptProject:
        validate_project(project)
        with self._lock:
            items = list(self._load_index_unlocked())
            index = next(
                (i for i, item in enumerate(items) if item.transcript_id == project.transcript_id),
                None,
            )
            if index is None:
                raise KeyError(project.transcript_id)
            current = self._get_unlocked(project.transcript_id) or items[index]
            self._check_revision(current, expected_revision)
            self._migrate_legacy_documents_unlocked(tuple(items))
            self._write_document_unlocked(project)
            items[index] = project
            self._save_index_unlocked(tuple(items))
        return project

    def mutate(
        self,
        transcript_id: str,
        operation: Callable[[TranscriptProject], TranscriptProject],
        *,
        expected_revision: int | None = None,
    ) -> TranscriptProject:
        with self._lock:
            items = list(self._load_index_unlocked())
            index = next(
                (i for i, item in enumerate(items) if item.transcript_id == transcript_id),
                None,
            )
            if index is None:
                raise KeyError(transcript_id)
            current = self._get_unlocked(transcript_id) or items[index]
            self._check_revision(current, expected_revision)
            updated = operation(current)
            validate_project(updated)
            self._migrate_legacy_documents_unlocked(tuple(items))
            self._write_document_unlocked(updated)
            items[index] = updated
            self._save_index_unlocked(tuple(items))
            return updated

    def delete(self, transcript_id: str) -> bool:
        with self._lock:
            items = self._load_index_unlocked()
            remaining = tuple(item for item in items if item.transcript_id != transcript_id)
            if len(remaining) == len(items):
                return False
            self._migrate_legacy_documents_unlocked(remaining)
            self._save_index_unlocked(remaining)
            self._document_path(transcript_id).unlink(missing_ok=True)
            artifact_dir = (self.artifacts_dir / transcript_id).resolve()
            if artifact_dir.parent == self.artifacts_dir.resolve():
                shutil.rmtree(artifact_dir, ignore_errors=True)
            return True

    def project_dir(self, transcript_id: str) -> Path:
        path = self.artifacts_dir / transcript_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _get_unlocked(self, transcript_id: str) -> TranscriptProject | None:
        payload = read_json(self._document_path(transcript_id))
        if isinstance(payload, dict):
            try:
                project = TranscriptProject.from_dict(payload)
                validate_project(project)
                return project
            except (KeyError, TypeError, ValueError):
                pass
        return next(
            (item for item in self._load_index_unlocked() if item.transcript_id == transcript_id),
            None,
        )

    def _load_index_unlocked(self) -> tuple[TranscriptProject, ...]:
        payload = read_json(self.path)
        if not isinstance(payload, dict) or not isinstance(payload.get("projects"), list):
            return ()
        projects: list[TranscriptProject] = []
        for item in payload["projects"]:
            if not isinstance(item, dict):
                continue
            try:
                project = TranscriptProject.from_dict(item)
                validate_project(project)
            except (KeyError, TypeError, ValueError):
                continue
            projects.append(project)
        return tuple(projects)

    def _migrate_legacy_documents_unlocked(
        self,
        projects: tuple[TranscriptProject, ...],
    ) -> None:
        for project in projects:
            path = self._document_path(project.transcript_id)
            if project.cues and not path.is_file():
                self._write_document_unlocked(project)

    def _write_document_unlocked(self, project: TranscriptProject) -> None:
        write_json_atomic(self._document_path(project.transcript_id), project.to_dict())

    def _save_index_unlocked(self, projects: tuple[TranscriptProject, ...]) -> None:
        write_json_atomic(
            self.path,
            {
                "schema_version": 2,
                "projects": [project.to_dict(include_cues=False) for project in projects],
            },
        )

    def _document_path(self, transcript_id: str) -> Path:
        safe_id = "".join(char for char in transcript_id if char.isalnum() or char in {"-", "_"})
        if not safe_id or safe_id != transcript_id:
            raise ValueError("Transcript ID không hợp lệ.")
        return self.documents_dir / f"{safe_id}.json"

    @staticmethod
    def _check_revision(
        current: TranscriptProject,
        expected_revision: int | None,
    ) -> None:
        if expected_revision is not None and current.revision != expected_revision:
            raise RevisionConflictError(
                f"Transcript đã thay đổi (bản hiện tại {current.revision}, "
                f"bản gửi lên {expected_revision})."
            )

    @staticmethod
    def _search_text(project: TranscriptProject) -> str:
        speakers = " ".join(speaker.label for speaker in project.speakers)
        cues = " ".join(cue.text for cue in project.cues)
        return f"{project.name} {project.source_path} {project.detected_language} {speakers} {cues}"
