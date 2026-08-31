"""Atomic local persistence for immutable native parity evidence."""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

from .models import CaseResult, CheckResult, SourceFingerprint
from .security import redact_report_value


RunStatus = Literal["running", "completed", "failed", "cancelled", "interrupted"]
TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
_RUN_STATUSES = TERMINAL_RUN_STATUSES | {"running"}
_SCHEMA_VERSION = 1


class ParityRepositoryError(RuntimeError):
    """Base error for parity evidence persistence."""


class ImmutableRunError(ParityRepositoryError):
    """Raised when code attempts to rewrite terminal automated evidence."""


@dataclass(frozen=True)
class ManualItem:
    item_id: str
    case_id: str
    prompt: str
    required: bool = True


@dataclass(frozen=True)
class ManualAnswer:
    item_id: str
    accepted: bool
    note: str
    answered_at: str


@dataclass(frozen=True)
class AcceptanceRecord:
    note: str
    accepted_at: str
    catalogue_hash: str
    manifest_hash: str


@dataclass(frozen=True)
class ParityRun:
    run_id: str
    task_id: str
    status: RunStatus
    catalogue_version: str
    catalogue_hash: str
    manifest_path: str
    manifest_hash: str
    app_version: str
    created_at: str
    report_json_path: str
    report_markdown_path: str
    required_case_ids: tuple[str, ...]
    manual_items: tuple[ManualItem, ...]
    thresholds: Mapping[str, Mapping[str, object]]
    source_fingerprints: Mapping[str, SourceFingerprint] = field(default_factory=dict)
    reference_fingerprints: Mapping[str, SourceFingerprint] = field(default_factory=dict)
    case_results: tuple[CaseResult, ...] = ()
    warnings: tuple[str, ...] = ()
    completed_at: str | None = None
    manual_answers: Mapping[str, ManualAnswer] = field(default_factory=dict)
    acceptance: AcceptanceRecord | None = None

    def __post_init__(self) -> None:
        if self.status not in _RUN_STATUSES:
            raise ValueError(f"Unknown parity run status: {self.status}")
        object.__setattr__(self, "required_case_ids", tuple(self.required_case_ids))
        object.__setattr__(self, "manual_items", tuple(self.manual_items))
        object.__setattr__(self, "case_results", tuple(self.case_results))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(
            self,
            "thresholds",
            MappingProxyType(
                {
                    str(case_id): MappingProxyType(dict(values))
                    for case_id, values in self.thresholds.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "source_fingerprints",
            MappingProxyType(dict(self.source_fingerprints)),
        )
        object.__setattr__(
            self,
            "reference_fingerprints",
            MappingProxyType(dict(self.reference_fingerprints)),
        )
        object.__setattr__(
            self,
            "manual_answers",
            MappingProxyType(dict(self.manual_answers)),
        )


def default_parity_store_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path(tempfile.gettempdir())
    return root / "GalaxyAIStudio" / "state" / "parity"


class ParityRepository:
    """Own run envelopes, mutable review overlays, and rendered reports."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_parity_store_path()
        self._lock = threading.RLock()

    def create_run(self, run: ParityRun) -> ParityRun:
        if run.status != "running" or run.case_results or run.completed_at is not None:
            raise ValueError("A new parity run must be empty and running")
        path = self._run_path(run.run_id)
        with self._lock:
            if path.exists():
                raise ImmutableRunError(f"Parity run already exists: {run.run_id}")
            _write_json_atomic(path, _run_payload(run))
        return run

    def record_case_result(self, run_id: str, result: CaseResult) -> ParityRun:
        """Checkpoint one new case while the automated run is still active."""

        with self._lock:
            run = self._require_run(run_id)
            if run.status != "running":
                raise ImmutableRunError(f"Automated evidence is immutable: {run_id}")
            if any(item.case_id == result.case_id for item in run.case_results):
                raise ImmutableRunError(f"Case evidence already exists: {result.case_id}")
            updated = replace(run, case_results=(*run.case_results, result))
            _write_json_atomic(self._run_path(run_id), _run_payload(updated))
            return updated

    def finish_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        case_results: tuple[CaseResult, ...],
        warnings: tuple[str, ...],
        completed_at: str,
    ) -> ParityRun:
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError(f"Terminal parity status required, got: {status}")
        with self._lock:
            run = self._require_run(run_id)
            if run.status != "running":
                raise ImmutableRunError(f"Automated evidence is immutable: {run_id}")
            checkpointed_ids = tuple(item.case_id for item in run.case_results)
            final_ids = tuple(item.case_id for item in case_results)
            if checkpointed_ids != final_ids[: len(checkpointed_ids)]:
                raise ImmutableRunError("Final evidence cannot rewrite checkpointed cases")
            if len(final_ids) != len(set(final_ids)):
                raise ValueError("Case results must have unique case IDs")
            updated = replace(
                run,
                status=status,
                case_results=tuple(case_results),
                warnings=tuple(str(item) for item in redact_report_value(warnings)),
                completed_at=completed_at,
            )
            _write_json_atomic(self._run_path(run_id), _run_payload(updated))
            return self._with_overlays(updated)

    def get_run(self, run_id: str) -> ParityRun | None:
        with self._lock:
            path = self._run_path(run_id)
            if not path.is_file():
                return None
            return self._with_overlays(_run_from_payload(_read_object(path)))

    def list_runs(self) -> tuple[ParityRun, ...]:
        with self._lock:
            if not self._runs_root.is_dir():
                return ()
            runs = [
                self._with_overlays(_run_from_payload(_read_object(path)))
                for path in self._runs_root.glob("*/run.json")
            ]
        return tuple(sorted(runs, key=lambda item: (item.created_at, item.run_id), reverse=True))

    def record_manual_answer(self, run_id: str, answer: ManualAnswer) -> ParityRun:
        with self._lock:
            run = self._require_run(run_id)
            if run.status == "running":
                raise ImmutableRunError("Manual evidence requires a terminal run")
            if self._acceptance_path(run_id).exists():
                raise ImmutableRunError("Manual evidence cannot change an accepted run")
            valid_ids = {item.item_id for item in run.manual_items}
            if answer.item_id not in valid_ids:
                raise KeyError(answer.item_id)
            answers = dict(self._load_manual_answers(run_id))
            answers[answer.item_id] = answer
            payload = {
                "schema_version": _SCHEMA_VERSION,
                "answers": [_manual_answer_payload(answers[key]) for key in sorted(answers)],
            }
            _write_json_atomic(self._manual_path(run_id), payload)
            return self._with_overlays(run)

    def record_acceptance(self, run_id: str, acceptance: AcceptanceRecord) -> ParityRun:
        with self._lock:
            run = self._require_run(run_id)
            path = self._acceptance_path(run_id)
            if path.exists():
                raise ImmutableRunError(f"Parity run is already accepted: {run_id}")
            _write_json_atomic(
                path,
                {
                    "schema_version": _SCHEMA_VERSION,
                    "acceptance": _acceptance_payload(acceptance),
                },
            )
            return self._with_overlays(run)

    def write_reports(self, run_id: str, json_bytes: bytes, markdown: str) -> None:
        if self.get_run(run_id) is None:
            raise KeyError(run_id)
        with self._lock:
            _write_bytes_atomic(self._report_path(run_id, "json"), json_bytes)
            _write_bytes_atomic(
                self._report_path(run_id, "markdown"),
                markdown.encode("utf-8"),
            )

    def read_report(self, run_id: str, report_format: str) -> bytes:
        path = self._report_path(run_id, report_format)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise FileNotFoundError(f"Parity report not found: {run_id}") from None

    @property
    def _runs_root(self) -> Path:
        return self.root / "runs"

    def _run_dir(self, run_id: str) -> Path:
        if not run_id or run_id in {".", ".."} or Path(run_id).name != run_id:
            raise ValueError("Invalid parity run ID")
        return self._runs_root / run_id

    def _run_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "run.json"

    def _manual_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "manual.json"

    def _acceptance_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "acceptance.json"

    def _report_path(self, run_id: str, report_format: str) -> Path:
        self._run_dir(run_id)
        suffixes = {"json": ".json", "markdown": ".md"}
        try:
            suffix = suffixes[report_format]
        except KeyError:
            raise ValueError(f"Unsupported parity report format: {report_format}") from None
        return self.root / "reports" / f"{run_id}{suffix}"

    def _require_run(self, run_id: str) -> ParityRun:
        path = self._run_path(run_id)
        if not path.is_file():
            raise KeyError(run_id)
        return _run_from_payload(_read_object(path))

    def _with_overlays(self, run: ParityRun) -> ParityRun:
        acceptance: AcceptanceRecord | None = None
        acceptance_path = self._acceptance_path(run.run_id)
        if acceptance_path.is_file():
            payload = _read_object(acceptance_path).get("acceptance")
            if not isinstance(payload, dict):
                raise ParityRepositoryError("Invalid parity acceptance overlay")
            acceptance = _acceptance_from_payload(payload)
        return replace(
            run,
            manual_answers=self._load_manual_answers(run.run_id),
            acceptance=acceptance,
        )

    def _load_manual_answers(self, run_id: str) -> Mapping[str, ManualAnswer]:
        path = self._manual_path(run_id)
        if not path.is_file():
            return {}
        payload = _read_object(path)
        raw_answers = payload.get("answers", [])
        if not isinstance(raw_answers, list):
            raise ParityRepositoryError("Invalid parity manual overlay")
        answers = (_manual_answer_from_payload(item) for item in raw_answers)
        return {answer.item_id: answer for answer in answers}


def _write_json_atomic(path: Path, payload: object) -> None:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    _write_bytes_atomic(path, encoded)


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as destination:
            temporary = Path(destination.name)
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ParityRepositoryError(f"Cannot read parity evidence: {path.name}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
        raise ParityRepositoryError(f"Unsupported parity evidence: {path.name}")
    return payload


def _run_payload(run: ParityRun) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "run_id": run.run_id,
        "task_id": run.task_id,
        "status": run.status,
        "catalogue_version": run.catalogue_version,
        "catalogue_hash": run.catalogue_hash,
        "manifest_path": run.manifest_path,
        "manifest_hash": run.manifest_hash,
        "app_version": run.app_version,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "report_json_path": run.report_json_path,
        "report_markdown_path": run.report_markdown_path,
        "required_case_ids": list(run.required_case_ids),
        "manual_items": [
            {
                "item_id": item.item_id,
                "case_id": item.case_id,
                "prompt": item.prompt,
                "required": item.required,
            }
            for item in run.manual_items
        ],
        "thresholds": _persistence_value(run.thresholds),
        "source_fingerprints": _fingerprints_payload(run.source_fingerprints),
        "reference_fingerprints": _fingerprints_payload(run.reference_fingerprints),
        "case_results": [_case_result_payload(item) for item in run.case_results],
        "warnings": list(redact_report_value(run.warnings)),
    }


def _run_from_payload(payload: Mapping[str, Any]) -> ParityRun:
    try:
        return ParityRun(
            run_id=str(payload["run_id"]),
            task_id=str(payload["task_id"]),
            status=str(payload["status"]),  # type: ignore[arg-type]
            catalogue_version=str(payload["catalogue_version"]),
            catalogue_hash=str(payload["catalogue_hash"]),
            manifest_path=str(payload["manifest_path"]),
            manifest_hash=str(payload["manifest_hash"]),
            app_version=str(payload["app_version"]),
            created_at=str(payload["created_at"]),
            completed_at=(
                str(payload["completed_at"])
                if payload.get("completed_at") is not None
                else None
            ),
            report_json_path=str(payload["report_json_path"]),
            report_markdown_path=str(payload["report_markdown_path"]),
            required_case_ids=tuple(str(item) for item in payload["required_case_ids"]),
            manual_items=tuple(
                ManualItem(
                    item_id=str(item["item_id"]),
                    case_id=str(item["case_id"]),
                    prompt=str(item["prompt"]),
                    required=bool(item.get("required", True)),
                )
                for item in payload["manual_items"]
            ),
            thresholds={
                str(key): dict(value)
                for key, value in dict(payload["thresholds"]).items()
            },
            source_fingerprints=_fingerprints_from_payload(
                payload.get("source_fingerprints", {})
            ),
            reference_fingerprints=_fingerprints_from_payload(
                payload.get("reference_fingerprints", {})
            ),
            case_results=tuple(
                _case_result_from_payload(item) for item in payload["case_results"]
            ),
            warnings=tuple(str(item) for item in payload.get("warnings", [])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ParityRepositoryError("Invalid parity run envelope") from error


def _case_result_payload(result: CaseResult) -> dict[str, Any]:
    safe = redact_report_value(
        {
            "case_id": result.case_id,
            "status": result.status,
            "checks": [
                {
                    "check_id": check.check_id,
                    "status": check.status,
                    "message": check.message,
                    "measurements": _persistence_value(check.measurements),
                }
                for check in result.checks
            ],
        }
    )
    return dict(safe)


def _persistence_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _persistence_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        normalized = [_persistence_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, (list, tuple)):
        return [_persistence_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value).casefold()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<binary:{len(value)} bytes>"
    if isinstance(value, Path):
        return redact_report_value(str(value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"<unsupported:{type(value).__name__}>"


def _case_result_from_payload(payload: Mapping[str, Any]) -> CaseResult:
    return CaseResult(
        case_id=str(payload["case_id"]),
        status=str(payload["status"]),  # type: ignore[arg-type]
        checks=tuple(
            CheckResult(
                check_id=str(item["check_id"]),
                status=str(item["status"]),  # type: ignore[arg-type]
                message=str(item["message"]),
                measurements=dict(item.get("measurements", {})),
            )
            for item in payload["checks"]
        ),
    )


def _fingerprints_payload(
    fingerprints: Mapping[str, SourceFingerprint],
) -> dict[str, dict[str, object]]:
    return {
        key: {
            "kind": value.kind,
            "sha256": value.sha256,
            "byte_size": value.byte_size,
            "entry_count": value.entry_count,
        }
        for key, value in fingerprints.items()
    }


def _fingerprints_from_payload(payload: Any) -> dict[str, SourceFingerprint]:
    if not isinstance(payload, Mapping):
        raise TypeError("Fingerprints must be an object")
    return {
        str(key): SourceFingerprint(
            kind=str(value["kind"]),
            sha256=str(value["sha256"]),
            byte_size=int(value["byte_size"]),
            entry_count=int(value["entry_count"]),
        )
        for key, value in payload.items()
    }


def _manual_answer_payload(answer: ManualAnswer) -> dict[str, object]:
    return dict(
        redact_report_value(
            {
                "item_id": answer.item_id,
                "accepted": answer.accepted,
                "note": answer.note,
                "answered_at": answer.answered_at,
            }
        )
    )


def _manual_answer_from_payload(payload: Mapping[str, Any]) -> ManualAnswer:
    if not isinstance(payload.get("accepted"), bool):
        raise ParityRepositoryError("Manual answer must contain a boolean decision")
    return ManualAnswer(
        item_id=str(payload["item_id"]),
        accepted=payload["accepted"],
        note=str(payload.get("note", "")),
        answered_at=str(payload["answered_at"]),
    )


def _acceptance_payload(acceptance: AcceptanceRecord) -> dict[str, str]:
    return dict(
        redact_report_value(
            {
                "note": acceptance.note,
                "accepted_at": acceptance.accepted_at,
                "catalogue_hash": acceptance.catalogue_hash,
                "manifest_hash": acceptance.manifest_hash,
            }
        )
    )


def _acceptance_from_payload(payload: Mapping[str, Any]) -> AcceptanceRecord:
    return AcceptanceRecord(
        note=str(payload["note"]),
        accepted_at=str(payload["accepted_at"]),
        catalogue_hash=str(payload["catalogue_hash"]),
        manifest_hash=str(payload["manifest_hash"]),
    )
