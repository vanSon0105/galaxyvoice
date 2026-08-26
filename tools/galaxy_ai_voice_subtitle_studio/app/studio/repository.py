from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..common.cache import read_json, write_json_atomic
from .models import StudioArtifact, StudioGenerationSpec, StudioTake, StudioTakeView


_repository_lock = threading.RLock()


class StudioTakeRepository:
    """Persistent takes with mutable annotations stored outside generation data."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def list(
        self,
        *,
        project_id: str = "",
        query: str = "",
        starred_only: bool = False,
    ) -> list[StudioTakeView]:
        query_value = query.strip().casefold()
        with _repository_lock:
            takes, starred_ids, primary_by_project = self._load()
        views = [self._view(item, starred_ids, primary_by_project) for item in takes]
        if project_id:
            views = [item for item in views if item.take.project_id == project_id]
        if starred_only:
            views = [item for item in views if item.starred]
        if query_value:
            views = [
                item
                for item in views
                if query_value in item.take.title.casefold()
                or query_value in item.take.spec.text.casefold()
                or query_value in item.take.spec.voice.profile_id.casefold()
            ]
        return sorted(views, key=lambda item: item.take.created_at, reverse=True)

    def get(self, take_id: str) -> StudioTakeView | None:
        with _repository_lock:
            takes, starred_ids, primary_by_project = self._load()
        take = next((item for item in takes if item.take_id == take_id), None)
        return self._view(take, starred_ids, primary_by_project) if take else None

    def add(
        self,
        spec: StudioGenerationSpec,
        artifact: StudioArtifact,
        *,
        generation_run_id: str,
        rerun_of: str = "",
    ) -> StudioTakeView:
        take = StudioTake(
            take_id=uuid.uuid4().hex,
            project_id=spec.project_id,
            title=spec.title.strip() or spec.output_name.strip() or "Bản đọc",
            engine_id=spec.engine_id,
            spec=spec,
            project_dir=str(artifact.project_dir),
            wav_path=str(artifact.wav_path),
            mp3_path=str(artifact.mp3_path) if artifact.mp3_path else "",
            manifest_path=str(artifact.manifest_path),
            profile_id=artifact.profile_id,
            warnings=artifact.warnings,
            generation_run_id=generation_run_id,
            rerun_of=rerun_of,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with _repository_lock:
            takes, starred_ids, primary_by_project = self._load()
            takes.append(take)
            self._save(takes, starred_ids, primary_by_project)
        return self._view(take, starred_ids, primary_by_project)

    def set_starred(self, take_id: str, starred: bool) -> StudioTakeView:
        with _repository_lock:
            takes, starred_ids, primary_by_project = self._load()
            take = self._require(takes, take_id)
            if starred:
                starred_ids.add(take_id)
            else:
                starred_ids.discard(take_id)
            self._save(takes, starred_ids, primary_by_project)
            return self._view(take, starred_ids, primary_by_project)

    def set_primary(self, take_id: str, primary: bool) -> StudioTakeView:
        with _repository_lock:
            takes, starred_ids, primary_by_project = self._load()
            take = self._require(takes, take_id)
            if primary:
                primary_by_project[take.project_id] = take_id
            elif primary_by_project.get(take.project_id) == take_id:
                primary_by_project.pop(take.project_id, None)
            self._save(takes, starred_ids, primary_by_project)
            return self._view(take, starred_ids, primary_by_project)

    def delete(self, take_id: str) -> None:
        with _repository_lock:
            takes, starred_ids, primary_by_project = self._load()
            takes = [item for item in takes if item.take_id != take_id]
            starred_ids.discard(take_id)
            primary_by_project = {
                project_id: selected_id
                for project_id, selected_id in primary_by_project.items()
                if selected_id != take_id
            }
            self._save(takes, starred_ids, primary_by_project)

    def resolve_audio(self, take_id: str, audio_format: str = "") -> Path:
        view = self.get(take_id)
        if view is None:
            raise KeyError(take_id)
        take = view.take
        requested = audio_format.strip().lower()
        if requested and requested not in take.spec.formats:
            raise FileNotFoundError(f"Take không xuất định dạng {requested.upper()}")
        if not requested:
            requested = "mp3" if "mp3" in take.spec.formats and take.mp3_path else "wav"
        selected = take.mp3_path if requested == "mp3" else take.wav_path
        path = Path(selected).resolve()
        project_dir = Path(take.project_dir).resolve()
        if (
            not selected
            or not path.is_relative_to(project_dir)
            or not path.is_file()
            or path.suffix.lower() not in (".wav", ".mp3")
        ):
            raise FileNotFoundError(selected)
        return path

    @staticmethod
    def _view(
        take: StudioTake,
        starred_ids: set[str],
        primary_by_project: dict[str, str],
    ) -> StudioTakeView:
        return StudioTakeView(
            take=take,
            starred=take.take_id in starred_ids,
            primary=primary_by_project.get(take.project_id) == take.take_id,
        )

    @staticmethod
    def _require(takes: list[StudioTake], take_id: str) -> StudioTake:
        take = next((item for item in takes if item.take_id == take_id), None)
        if take is None:
            raise KeyError(take_id)
        return take

    def _load(self) -> tuple[list[StudioTake], set[str], dict[str, str]]:
        payload = read_json(self.path)
        if not isinstance(payload, dict) or not isinstance(payload.get("takes"), list):
            return [], set(), {}
        takes: list[StudioTake] = []
        starred_ids = {str(item) for item in payload.get("starred_take_ids") or () if str(item)}
        primary_by_project = {
            str(key): str(value)
            for key, value in dict(payload.get("primary_take_by_project") or {}).items()
            if str(key) and str(value)
        }
        for raw in payload["takes"]:
            if not isinstance(raw, dict):
                continue
            try:
                take = self._from_payload(raw)
            except (TypeError, ValueError):
                continue
            takes.append(take)
            # Schema v1 migration: lift mutable flags out of the take record.
            if raw.get("starred"):
                starred_ids.add(take.take_id)
            if raw.get("primary") and take.project_id:
                primary_by_project[take.project_id] = take.take_id
        valid_ids = {item.take_id for item in takes}
        starred_ids.intersection_update(valid_ids)
        primary_by_project = {
            project_id: take_id
            for project_id, take_id in primary_by_project.items()
            if take_id in valid_ids
        }
        return takes, starred_ids, primary_by_project

    def _save(
        self,
        takes: list[StudioTake],
        starred_ids: set[str],
        primary_by_project: dict[str, str],
    ) -> None:
        retained = takes[-2000:]
        retained_ids = {item.take_id for item in retained}
        write_json_atomic(
            self.path,
            {
                "schema_version": 2,
                "takes": [self._to_payload(item) for item in retained],
                "starred_take_ids": sorted(starred_ids & retained_ids),
                "primary_take_by_project": {
                    project_id: take_id
                    for project_id, take_id in primary_by_project.items()
                    if take_id in retained_ids
                },
            },
        )

    @staticmethod
    def _to_payload(item: StudioTake) -> dict[str, Any]:
        return {
            "take_id": item.take_id,
            "project_id": item.project_id,
            "title": item.title,
            "engine_id": item.engine_id,
            "spec": item.spec.to_payload(),
            "project_dir": item.project_dir,
            "wav_path": item.wav_path,
            "mp3_path": item.mp3_path,
            "manifest_path": item.manifest_path,
            "profile_id": item.profile_id,
            "warnings": list(item.warnings),
            "generation_run_id": item.generation_run_id,
            "rerun_of": item.rerun_of,
            "created_at": item.created_at,
        }

    @staticmethod
    def _from_payload(payload: dict[str, Any]) -> StudioTake:
        spec_payload = payload.get("spec") if isinstance(payload.get("spec"), dict) else {}
        spec = StudioGenerationSpec.from_payload(spec_payload)
        return StudioTake(
            take_id=str(payload.get("take_id") or ""),
            project_id=str(payload.get("project_id") or spec.project_id),
            title=str(payload.get("title") or spec.title or "Bản đọc"),
            engine_id=str(payload.get("engine_id") or spec.engine_id),
            spec=spec,
            project_dir=str(payload.get("project_dir") or ""),
            wav_path=str(payload.get("wav_path") or ""),
            mp3_path=str(payload.get("mp3_path") or ""),
            manifest_path=str(payload.get("manifest_path") or ""),
            profile_id=str(payload.get("profile_id") or ""),
            warnings=tuple(str(item) for item in payload.get("warnings") or ()),
            generation_run_id=str(payload.get("generation_run_id") or ""),
            rerun_of=str(payload.get("rerun_of") or ""),
            created_at=str(payload.get("created_at") or ""),
        )
