from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..common.cache import read_json, write_json_atomic
from ..common.paths import unique_project_dir
from ..studio.models import StudioArtifact
from .models import BatchItemSpec, BatchItemState, BatchRun, BatchSpec


_lock = threading.RLock()


class BatchRepository:
    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path

    def create(self, spec: BatchSpec, items: tuple[BatchItemSpec, ...]) -> BatchRun:
        spec.validate()
        root = unique_project_dir(Path(spec.output_dir).expanduser(), spec.title, "galaxy-batch")
        now = _now()
        run = BatchRun(
            batch_id=uuid.uuid4().hex,
            spec=spec,
            root_dir=str(root),
            manifest_path=str(root / "batch.manifest.json"),
            local_path=str(root / "batch.local.json"),
            items=[BatchItemState(item) for item in items],
            created_at=now,
            updated_at=now,
        )
        with _lock:
            self._save_run(run)
            index = self._load_index()
            index[run.batch_id] = run.local_path
            self._save_index(index)
        return run

    def list(self, *, project_id: str = "") -> list[BatchRun]:
        with _lock:
            runs = [run for path in self._load_index().values() if (run := self._load_local(Path(path)))]
        if project_id:
            runs = [run for run in runs if run.spec.project_id == project_id]
        return sorted(runs, key=lambda run: run.updated_at, reverse=True)

    def get(self, batch_id: str) -> BatchRun | None:
        with _lock:
            path = self._load_index().get(batch_id)
            return self._load_local(Path(path)) if path else None

    def save(self, run: BatchRun) -> None:
        run.updated_at = _now()
        with _lock:
            self._save_run(run)

    def set_task(self, batch_id: str, task_id: str) -> BatchRun:
        run = self.require(batch_id)
        run.task_id = task_id
        run.status = "queued"
        self.save(run)
        return run

    def require(self, batch_id: str) -> BatchRun:
        run = self.get(batch_id)
        if run is None:
            raise KeyError(batch_id)
        return run

    def prepare_resume(self, batch_id: str, *, retry_failed: bool) -> BatchRun:
        run = self.require(batch_id)
        eligible = False
        for item in run.items:
            should_reset = item.status == "failed" if retry_failed else item.status in {"pending", "running"}
            if should_reset:
                eligible = True
                item.status = "pending"
                item.error = ""
        if not eligible:
            message = "Batch không có mục lỗi để thử lại." if retry_failed else "Batch không còn mục đang chờ để tiếp tục."
            raise ValueError(message)
        run.combined_wav_path = ""
        run.combined_mp3_path = ""
        self.save(run)
        return run

    def recover_stale(self, active_task_ids: set[str]) -> None:
        for run in self.list():
            if run.status not in {"queued", "running", "paused"} or run.task_id in active_task_ids:
                continue
            run.status = "interrupted"
            for item in run.items:
                if item.status == "running":
                    item.status = "pending"
            self.save(run)

    def record_artifact(self, run: BatchRun, item: BatchItemState, artifact: StudioArtifact) -> None:
        root = Path(run.root_dir).resolve()
        item.project_dir = self._relative(artifact.project_dir, root)
        item.wav_path = self._relative(artifact.wav_path, root)
        item.mp3_path = self._relative(artifact.mp3_path, root) if artifact.mp3_path else ""
        item.manifest_path = self._relative(artifact.manifest_path, root)
        item.warnings = artifact.warnings

    def resolve_artifact(self, batch_id: str, kind: str, item_id: str = "") -> Path:
        run = self.require(batch_id)
        if item_id:
            item = next((value for value in run.items if value.spec.item_id == item_id), None)
            if item is None:
                raise KeyError(item_id)
            selected = item.mp3_path if kind == "mp3" else item.wav_path
        elif kind == "manifest":
            selected = Path(run.manifest_path).name
        else:
            selected = run.combined_mp3_path if kind == "mp3" else run.combined_wav_path
        if not selected:
            raise FileNotFoundError(kind)
        root = Path(run.root_dir).resolve()
        path = (root / selected).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise FileNotFoundError(path)
        return path

    def _save_run(self, run: BatchRun) -> None:
        write_json_atomic(Path(run.local_path), self._local_payload(run))
        write_json_atomic(Path(run.manifest_path), self._portable_payload(run))

    def _load_local(self, path: Path) -> BatchRun | None:
        payload = read_json(path)
        if not isinstance(payload, dict):
            return None
        try:
            spec = BatchSpec.from_payload(dict(payload["spec"]))
            items = [self._item_from_payload(item) for item in payload.get("items", [])]
            return BatchRun(
                batch_id=str(payload["batch_id"]),
                spec=spec,
                root_dir=str(path.parent),
                manifest_path=str(path.parent / "batch.manifest.json"),
                local_path=str(path),
                items=items,
                status=str(payload.get("status") or "interrupted"),
                task_id=str(payload.get("task_id") or ""),
                combined_wav_path=str(payload.get("combined_wav_path") or ""),
                combined_mp3_path=str(payload.get("combined_mp3_path") or ""),
                warnings=[str(value) for value in payload.get("warnings") or []],
                created_at=str(payload.get("created_at") or ""),
                updated_at=str(payload.get("updated_at") or ""),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _item_from_payload(payload: dict[str, Any]) -> BatchItemState:
        return BatchItemState(
            spec=BatchItemSpec.from_payload(dict(payload.get("spec") or {})),
            status=str(payload.get("status") or "pending"),
            attempts=int(payload.get("attempts") or 0),
            error=str(payload.get("error") or ""),
            project_dir=str(payload.get("project_dir") or ""),
            wav_path=str(payload.get("wav_path") or ""),
            mp3_path=str(payload.get("mp3_path") or ""),
            manifest_path=str(payload.get("manifest_path") or ""),
            warnings=tuple(str(value) for value in payload.get("warnings") or ()),
        )

    @staticmethod
    def _local_payload(run: BatchRun) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "batch_id": run.batch_id,
            "status": run.status,
            "task_id": run.task_id,
            "spec": run.spec.to_payload(),
            "items": [_item_payload(item) for item in run.items],
            "combined_wav_path": run.combined_wav_path,
            "combined_mp3_path": run.combined_mp3_path,
            "warnings": run.warnings,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }

    @staticmethod
    def _portable_payload(run: BatchRun) -> dict[str, Any]:
        spec = run.spec.to_payload()
        spec.pop("output_dir", None)
        voice = dict(spec.get("voice") or {})
        if voice.get("reference_audio"):
            voice["reference_audio"] = Path(str(voice["reference_audio"])).name
            voice["reference_audio_external"] = True
        spec["voice"] = voice
        return {
            "schema_version": 1,
            "kind": "galaxy_voice_batch",
            "batch_id": run.batch_id,
            "project_id": run.spec.project_id,
            "status": run.status,
            "spec": spec,
            "items": [_item_payload(item) for item in run.items],
            "combined_wav_path": run.combined_wav_path or None,
            "combined_mp3_path": run.combined_mp3_path or None,
            "warnings": run.warnings,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }

    def _load_index(self) -> dict[str, str]:
        payload = read_json(self.index_path)
        if not isinstance(payload, dict) or not isinstance(payload.get("runs"), dict):
            return {}
        return {str(key): str(value) for key, value in payload["runs"].items()}

    def _save_index(self, runs: dict[str, str]) -> None:
        write_json_atomic(self.index_path, {"schema_version": 1, "runs": runs})

    @staticmethod
    def _relative(path: Path, root: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"Artifact Batch nằm ngoài thư mục Batch: {path}")
        return resolved.relative_to(root).as_posix()


def _item_payload(item: BatchItemState) -> dict[str, Any]:
    return {
        "spec": item.spec.to_payload(),
        "status": item.status,
        "attempts": item.attempts,
        "error": item.error or None,
        "project_dir": item.project_dir or None,
        "wav_path": item.wav_path or None,
        "mp3_path": item.mp3_path or None,
        "manifest_path": item.manifest_path or None,
        "warnings": list(item.warnings),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
