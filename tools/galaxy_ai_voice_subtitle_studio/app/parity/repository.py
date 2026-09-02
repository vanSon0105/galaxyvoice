"""Transactional local persistence for immutable native parity evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
import threading
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

from .models import CaseResult, CheckResult, SourceFingerprint
from .security import UnsafePathError, fingerprint_source, redact_report_value


RunStatus = Literal["running", "completed", "failed", "cancelled", "interrupted"]
TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
_RUN_STATUSES = TERMINAL_RUN_STATUSES | {"running"}
_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_REPOSITORY_LOCK = threading.RLock()


class ParityRepositoryError(RuntimeError):
    """Base error for unavailable or corrupt parity evidence."""


class ImmutableRunError(ParityRepositoryError):
    """Raised when immutable evidence or a validated snapshot changed."""


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
class ThresholdOverride:
    case_id: str
    threshold_id: str
    catalogue_value: object
    override_value: object
    provenance: str
    note: str
    relaxation: bool


@dataclass(frozen=True)
class AcceptanceRecord:
    note: str
    accepted_at: str
    catalogue_hash: str
    manifest_hash: str
    run_revision: str = ""
    manual_revision: str = ""
    input_revision: str = ""
    report_revision: str = ""


@dataclass(frozen=True)
class ParityRun:
    run_id: str
    task_id: str
    status: RunStatus
    catalogue_version: str
    catalogue_hash: str
    manifest_path: str
    manifest_hash: str
    manifest_snapshot_path: str
    app_version: str
    created_at: str
    report_json_path: str
    report_markdown_path: str
    required_case_ids: tuple[str, ...]
    manual_items: tuple[ManualItem, ...]
    thresholds: Mapping[str, Mapping[str, object]]
    threshold_overrides: tuple[ThresholdOverride, ...] = ()
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
        object.__setattr__(self, "threshold_overrides", tuple(self.threshold_overrides))
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
        object.__setattr__(self, "manual_answers", MappingProxyType(dict(self.manual_answers)))


@dataclass(frozen=True)
class AcceptanceSnapshot:
    run: ParityRun
    run_revision: str
    manual_revision: str
    input_revision: str
    selected_source_path: str
    selected_source_fingerprint: SourceFingerprint


def default_parity_store_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path(tempfile.gettempdir())
    return root / "GalaxyAIStudio" / "state" / "parity"


class ParityRepository:
    """Own run snapshots, review transactions, and report revisions."""

    def __init__(self, root: Path | None = None) -> None:
        selected = Path(root) if root is not None else default_parity_store_path()
        self.root = selected.expanduser().absolute()
        self._lock = _REPOSITORY_LOCK

    def create_run(self, run: ParityRun, *, manifest_bytes: bytes) -> ParityRun:
        if run.status != "running" or run.case_results or run.completed_at is not None:
            raise ValueError("A new parity run must be empty and running")
        if run.manifest_snapshot_path != "inputs/manifest.json":
            raise ValueError("Run-owned manifest snapshot path is fixed")
        if _digest(manifest_bytes) != run.manifest_hash:
            raise ValueError("Manifest snapshot bytes do not match the run hash")
        with self._lock:
            runs_root = self._mkdir_managed("runs")
            target = self._managed_path("runs", _validate_run_id(run.run_id))
            if _lexists(target):
                if _is_link_like(target.lstat()):
                    raise ImmutableRunError("Run path is a link or reparse point")
                raise ImmutableRunError(f"Parity run already exists: {run.run_id}")
            staging = runs_root / f".run-{uuid.uuid4().hex}.tmp"
            staging.mkdir()
            try:
                inputs = staging / "inputs"
                inputs.mkdir()
                _write_bytes_atomic(inputs / "manifest.json", bytes(manifest_bytes))
                _write_json_atomic(staging / "run.json", _run_payload(run))
                os.replace(staging, target)
                self._managed_path("runs", run.run_id, "run.json")
            finally:
                if _lexists(staging):
                    shutil.rmtree(staging)
        return run

    def manifest_snapshot_path(self, run_id: str) -> Path:
        with self._lock:
            run = self._require_run(run_id)
            path = self._managed_path("runs", run.run_id, "inputs", "manifest.json")
            self._require_regular_file(path, "Manifest snapshot")
            return path

    def record_case_result(self, run_id: str, result: CaseResult) -> ParityRun:
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
            checkpointed = run.case_results
            final = tuple(case_results)
            if checkpointed != final[: len(checkpointed)]:
                raise ImmutableRunError("Final evidence cannot rewrite checkpointed cases")
            case_ids = tuple(item.case_id for item in final)
            if len(case_ids) != len(set(case_ids)):
                raise ValueError("Case results must have unique case IDs")
            updated = replace(
                run,
                status=status,
                case_results=final,
                warnings=tuple(str(item) for item in redact_report_value(warnings)),
                completed_at=completed_at,
            )
            _write_json_atomic(self._run_path(run_id), _run_payload(updated))
            return self._with_overlays(updated)

    def get_run(self, run_id: str) -> ParityRun | None:
        with self._lock:
            try:
                return self._with_overlays(self._require_run(run_id))
            except (KeyError, OSError, ParityRepositoryError, ValueError):
                return None

    def list_runs(self) -> tuple[ParityRun, ...]:
        with self._lock:
            try:
                runs_root = self._managed_path("runs")
            except (OSError, ParityRepositoryError, ValueError):
                return ()
            if not runs_root.is_dir():
                return ()
            runs: list[ParityRun] = []
            try:
                entries = tuple(os.scandir(runs_root))
            except OSError:
                return ()
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                    if _is_link_like(info) or not stat.S_ISDIR(info.st_mode):
                        continue
                    run = self.get_run(entry.name)
                except (OSError, ValueError, ParityRepositoryError):
                    continue
                if run is not None:
                    runs.append(run)
        return tuple(sorted(runs, key=lambda item: (item.created_at, item.run_id), reverse=True))

    def record_manual_answer(self, run_id: str, answer: ManualAnswer) -> ParityRun:
        with self._lock:
            run = self._require_run(run_id)
            if run.status == "running":
                raise ImmutableRunError("Manual evidence requires a terminal run")
            if self._acceptance_path(run_id).is_file():
                raise ImmutableRunError("Manual evidence cannot change an accepted run")
            valid_ids = {item.item_id for item in run.manual_items}
            if answer.item_id not in valid_ids:
                raise KeyError(answer.item_id)
            _validate_manual_answer(answer)
            answers = dict(self._load_manual_answers(run))
            answers[answer.item_id] = answer
            _write_json_atomic(
                self._manual_path(run_id),
                {
                    "schema_version": _SCHEMA_VERSION,
                    "answers": [_manual_answer_payload(answers[key]) for key in sorted(answers)],
                },
            )
            return self._with_overlays(run)

    def acceptance_snapshot(self, run_id: str) -> AcceptanceSnapshot:
        with self._lock:
            return self._acceptance_snapshot_unlocked(run_id)

    def prepare_acceptance(
        self,
        snapshot: AcceptanceSnapshot,
        acceptance: AcceptanceRecord,
    ) -> AcceptanceRecord:
        """Persist retry identity without making the run accepted."""
        with self._lock:
            current = self._require_matching_snapshot_unlocked(snapshot)
            if current.run.acceptance is not None:
                raise ImmutableRunError(
                    f"Parity run is already accepted: {snapshot.run.run_id}"
                )
            prepared = replace(
                acceptance,
                run_revision=current.run_revision,
                manual_revision=current.manual_revision,
                input_revision=current.input_revision,
                report_revision="",
            )
            desired = _acceptance_intent_payload(prepared)
            path = self._acceptance_intent_path(current.run.run_id)
            if _lexists(path):
                existing = _acceptance_intent_from_payload(
                    _read_object(path, set(desired))
                )
                existing_identity = _acceptance_intent_payload(
                    replace(existing, accepted_at=prepared.accepted_at)
                )
                if existing_identity == desired:
                    return existing
            _write_json_atomic(path, desired)
            return prepared

    def commit_acceptance(
        self,
        snapshot: AcceptanceSnapshot,
        acceptance: AcceptanceRecord,
        *,
        json_bytes: bytes,
        markdown: str,
    ) -> ParityRun:
        with self._lock:
            current = self._require_matching_snapshot_unlocked(snapshot)
            if current.run.acceptance is not None:
                raise ImmutableRunError(f"Parity run is already accepted: {snapshot.run.run_id}")
            if acceptance.catalogue_hash != current.run.catalogue_hash:
                raise ImmutableRunError("Catalogue hash changed during acceptance")
            if acceptance.manifest_hash != current.run.manifest_hash:
                raise ImmutableRunError("Manifest hash changed during acceptance")
            committed = replace(
                acceptance,
                run_revision=current.run_revision,
                manual_revision=current.manual_revision,
                input_revision=current.input_revision,
            )
            _validate_acceptance(committed)
            intent = _acceptance_intent_from_payload(
                _read_object(
                    self._acceptance_intent_path(current.run.run_id),
                    set(_acceptance_intent_payload(replace(committed, report_revision=""))),
                )
            )
            if _acceptance_intent_payload(intent) != _acceptance_intent_payload(
                replace(committed, report_revision="")
            ):
                raise ImmutableRunError("Acceptance retry identity changed")
            self._stage_report_revision_unlocked(
                current.run.run_id,
                json_bytes,
                markdown.encode("utf-8"),
                committed.report_revision,
            )
            _write_json_atomic(
                self._acceptance_path(current.run.run_id),
                {"schema_version": _SCHEMA_VERSION, "acceptance": _acceptance_payload(committed)},
            )
            try:
                self._acceptance_intent_path(current.run.run_id).unlink(missing_ok=True)
            except OSError:
                pass
            return self._with_overlays(current.run)

    def record_acceptance(self, run_id: str, acceptance: AcceptanceRecord) -> ParityRun:
        snapshot = self.acceptance_snapshot(run_id)
        from .reports import render_reports

        committed = self.prepare_acceptance(snapshot, replace(
            acceptance,
            run_revision=snapshot.run_revision,
            manual_revision=snapshot.manual_revision,
            input_revision=snapshot.input_revision,
        ))
        draft = replace(snapshot.run, acceptance=committed)
        revision_input = render_reports(
            replace(draft, report_json_path="", report_markdown_path="")
        )
        revision = _digest(
            revision_input.json_bytes + b"\0" + revision_input.markdown.encode("utf-8")
        )
        committed = replace(committed, report_revision=revision)
        json_path, markdown_path = self.report_revision_paths(run_id, revision)
        rendered = render_reports(
            replace(
                draft,
                acceptance=committed,
                report_json_path=json_path,
                report_markdown_path=markdown_path,
            )
        )
        return self.commit_acceptance(
            snapshot,
            committed,
            json_bytes=rendered.json_bytes,
            markdown=rendered.markdown,
        )

    def report_revision_paths(self, run_id: str, revision: str) -> tuple[str, str]:
        validated_run_id = _validate_run_id(run_id)
        validated_revision = _hash_string(revision, "report revision")
        base = Path("reports") / validated_run_id / "revisions" / validated_revision
        return (
            (base / "report.json").as_posix(),
            (base / "report.md").as_posix(),
        )

    def write_reports(
        self,
        run_id: str,
        json_bytes: bytes,
        markdown: str,
        *,
        revision: str | None = None,
    ) -> tuple[str, str]:
        markdown_bytes = markdown.encode("utf-8")
        revision = revision or _digest(json_bytes + b"\0" + markdown_bytes)
        json_path, markdown_path = self.report_revision_paths(run_id, revision)
        with self._lock:
            try:
                self._require_run(run_id)
            except (KeyError, OSError, ParityRepositoryError, ValueError):
                raise KeyError(run_id)
            report_root = self._mkdir_managed("reports", _validate_run_id(run_id))
            self._stage_report_revision_unlocked(
                run_id,
                bytes(json_bytes),
                markdown_bytes,
                revision,
            )
            _write_json_atomic(
                report_root / "current.json",
                {
                    "schema_version": _SCHEMA_VERSION,
                    "revision": revision,
                    "json_path": json_path,
                    "markdown_path": markdown_path,
                },
            )
        return json_path, markdown_path

    def read_report(self, run_id: str, report_format: str) -> bytes:
        suffixes = {"json": "report.json", "markdown": "report.md"}
        try:
            filename = suffixes[report_format]
        except KeyError:
            raise ValueError(f"Unsupported parity report format: {report_format}") from None
        with self._lock:
            run = self.get_run(run_id)
            if run is None:
                raise FileNotFoundError(f"Parity report not found: {run_id}")
            try:
                if run.acceptance is not None:
                    revision = run.acceptance.report_revision
                else:
                    pointer = self._report_pointer_unlocked(run_id)
                    if pointer is None:
                        raise FileNotFoundError(run_id)
                    revision, _, _ = pointer
                revision_dir = self._managed_path("reports", run_id, "revisions", revision)
                return (revision_dir / filename).read_bytes()
            except (FileNotFoundError, OSError, ParityRepositoryError, ValueError):
                raise FileNotFoundError(f"Parity report not found: {run_id}") from None

    def _acceptance_snapshot_unlocked(self, run_id: str) -> AcceptanceSnapshot:
        run_path = self._run_path(run_id)
        run_bytes = self._read_regular_bytes(run_path, "Run envelope")
        run = _run_from_payload(_decode_object(run_bytes, run_path.name))
        run = self._with_overlays(run, run_bytes=run_bytes)
        manual_bytes = self._optional_regular_bytes(self._manual_path(run_id), "Manual overlay")
        input_path = self._managed_path("runs", run_id, "inputs", "manifest.json")
        input_bytes = self._read_regular_bytes(input_path, "Manifest snapshot")
        input_revision = _digest(input_bytes)
        if input_revision != run.manifest_hash:
            raise ImmutableRunError("Run-owned manifest revision changed")
        selected_source_fingerprint = _fingerprint_selected_manifest(run)
        return AcceptanceSnapshot(
            run=run,
            run_revision=_digest(run_bytes),
            manual_revision=_digest(manual_bytes),
            input_revision=input_revision,
            selected_source_path=run.manifest_path,
            selected_source_fingerprint=selected_source_fingerprint,
        )

    def _require_matching_snapshot_unlocked(
        self,
        snapshot: AcceptanceSnapshot,
    ) -> AcceptanceSnapshot:
        current = self._acceptance_snapshot_unlocked(snapshot.run.run_id)
        if (
            current.run_revision != snapshot.run_revision
            or current.manual_revision != snapshot.manual_revision
            or current.input_revision != snapshot.input_revision
            or current.selected_source_path != snapshot.selected_source_path
            or current.selected_source_fingerprint != snapshot.selected_source_fingerprint
        ):
            raise ImmutableRunError("Parity evidence changed during acceptance")
        return current

    def _require_run(self, run_id: str) -> ParityRun:
        path = self._run_path(run_id)
        run = _run_from_payload(_read_object(path, _RUN_FIELDS))
        if run.run_id != run_id:
            raise ParityRepositoryError("Run directory and envelope ID differ")
        return run

    def _with_overlays(self, run: ParityRun, *, run_bytes: bytes | None = None) -> ParityRun:
        report_pointer = self._report_pointer_unlocked(run.run_id)
        if report_pointer is not None:
            _, json_path, markdown_path = report_pointer
            run = replace(
                run,
                report_json_path=json_path,
                report_markdown_path=markdown_path,
            )
        answers = self._load_manual_answers(run)
        acceptance: AcceptanceRecord | None = None
        path = self._acceptance_path(run.run_id)
        if _lexists(path):
            payload = _read_object(path, {"schema_version", "acceptance"})
            raw = payload["acceptance"]
            if not isinstance(raw, Mapping):
                raise ParityRepositoryError("Invalid parity acceptance overlay")
            acceptance = _acceptance_from_payload(raw)
            actual_run_bytes = run_bytes or self._read_regular_bytes(
                self._run_path(run.run_id), "Run envelope"
            )
            manual_bytes = self._optional_regular_bytes(
                self._manual_path(run.run_id), "Manual overlay"
            )
            input_bytes = self._read_regular_bytes(
                self._managed_path("runs", run.run_id, "inputs", "manifest.json"),
                "Manifest snapshot",
            )
            if acceptance.catalogue_hash != run.catalogue_hash:
                raise ParityRepositoryError("Accepted catalogue hash does not match the run")
            if acceptance.manifest_hash != run.manifest_hash:
                raise ParityRepositoryError("Accepted manifest hash does not match the run")
            if acceptance.run_revision != _digest(actual_run_bytes):
                raise ParityRepositoryError("Accepted run revision changed")
            if acceptance.manual_revision != _digest(manual_bytes):
                raise ParityRepositoryError("Accepted manual revision changed")
            if acceptance.input_revision != _digest(input_bytes):
                raise ParityRepositoryError("Accepted input revision changed")
            revision_dir = self._managed_path(
                "reports", run.run_id, "revisions", acceptance.report_revision
            )
            self._require_regular_file(revision_dir / "report.json", "Accepted JSON report")
            self._require_regular_file(revision_dir / "report.md", "Accepted Markdown report")
            json_path, markdown_path = self.report_revision_paths(
                run.run_id,
                acceptance.report_revision,
            )
            run = replace(
                run,
                report_json_path=json_path,
                report_markdown_path=markdown_path,
            )
        return replace(run, manual_answers=answers, acceptance=acceptance)

    def _stage_report_revision_unlocked(
        self,
        run_id: str,
        json_bytes: bytes,
        markdown_bytes: bytes,
        revision: str,
    ) -> None:
        revision = _hash_string(revision, "report revision")
        revisions = self._mkdir_managed("reports", run_id, "revisions")
        revision_dir = self._managed_path("reports", run_id, "revisions", revision)
        if not _lexists(revision_dir):
            staging = revisions / f".revision-{uuid.uuid4().hex}.tmp"
            staging.mkdir()
            try:
                _write_bytes_atomic(staging / "report.json", bytes(json_bytes))
                _write_bytes_atomic(staging / "report.md", markdown_bytes)
                os.replace(staging, revision_dir)
            finally:
                if _lexists(staging):
                    shutil.rmtree(staging)
        else:
            self._require_plain_directory(revision_dir, "Report revision")
            self._require_regular_file(revision_dir / "report.json", "JSON report")
            self._require_regular_file(revision_dir / "report.md", "Markdown report")
            if (
                (revision_dir / "report.json").read_bytes() != json_bytes
                or (revision_dir / "report.md").read_bytes() != markdown_bytes
            ):
                raise ParityRepositoryError("Report revision content mismatch")
        self._require_regular_file(revision_dir / "report.json", "JSON report")
        self._require_regular_file(revision_dir / "report.md", "Markdown report")

    def _report_pointer_unlocked(
        self,
        run_id: str,
    ) -> tuple[str, str, str] | None:
        pointer_path = self._managed_path(
            "reports",
            _validate_run_id(run_id),
            "current.json",
        )
        if not _lexists(pointer_path):
            return None
        pointer = _read_object(
            pointer_path,
            {"schema_version", "revision", "json_path", "markdown_path"},
        )
        revision = _hash_string(pointer["revision"], "report revision")
        expected_json, expected_markdown = self.report_revision_paths(run_id, revision)
        if pointer["json_path"] != expected_json or pointer["markdown_path"] != expected_markdown:
            raise ParityRepositoryError("Published report paths do not match the revision")
        revision_dir = self._managed_path("reports", run_id, "revisions", revision)
        self._require_plain_directory(revision_dir, "Report revision")
        self._require_regular_file(revision_dir / "report.json", "JSON report")
        self._require_regular_file(revision_dir / "report.md", "Markdown report")
        return revision, expected_json, expected_markdown

    def _load_manual_answers(self, run: ParityRun) -> Mapping[str, ManualAnswer]:
        path = self._manual_path(run.run_id)
        if not _lexists(path):
            return {}
        payload = _read_object(path, {"schema_version", "answers"})
        raw_answers = payload["answers"]
        if not isinstance(raw_answers, list):
            raise ParityRepositoryError("Manual answers must be an array")
        valid_ids = {item.item_id for item in run.manual_items}
        answers: dict[str, ManualAnswer] = {}
        for raw in raw_answers:
            if not isinstance(raw, Mapping):
                raise ParityRepositoryError("Manual answer must be an object")
            answer = _manual_answer_from_payload(raw)
            if answer.item_id in answers:
                raise ParityRepositoryError(f"Duplicate manual answer: {answer.item_id}")
            if answer.item_id not in valid_ids:
                raise ParityRepositoryError(f"Unknown manual answer: {answer.item_id}")
            answers[answer.item_id] = answer
        return answers

    def _run_path(self, run_id: str) -> Path:
        return self._managed_path("runs", _validate_run_id(run_id), "run.json")

    def _manual_path(self, run_id: str) -> Path:
        return self._managed_path("runs", _validate_run_id(run_id), "manual.json")

    def _acceptance_path(self, run_id: str) -> Path:
        return self._managed_path("runs", _validate_run_id(run_id), "acceptance.json")

    def _acceptance_intent_path(self, run_id: str) -> Path:
        return self._managed_path(
            "runs",
            _validate_run_id(run_id),
            "acceptance.pending.json",
        )

    def _prepare_root(self) -> Path:
        prefixes = _absolute_path_prefixes(self.root)
        missing_ancestor = False
        for ancestor in prefixes:
            if missing_ancestor:
                if _lexists(ancestor):
                    raise ParityRepositoryError(
                        "Parity state ancestor appeared beneath a missing parent"
                    )
                continue
            try:
                info = ancestor.lstat()
            except FileNotFoundError:
                missing_ancestor = True
                continue
            if _is_link_like(info):
                raise ParityRepositoryError(
                    f"Parity state ancestor is a link or reparse point: {ancestor}"
                )
            if not stat.S_ISDIR(info.st_mode):
                raise ParityRepositoryError(
                    f"Parity state ancestor is not a directory: {ancestor}"
                )

        for ancestor in prefixes:
            if not _lexists(ancestor):
                ancestor.mkdir()
            self._require_plain_directory(ancestor, "Parity state ancestor")
        return self.root.resolve(strict=True)

    def _managed_path(self, *parts: str) -> Path:
        root = self._prepare_root()
        current = root
        for part in parts:
            if not part or part in {".", ".."} or Path(part).name != part:
                raise ValueError("Managed path components must be confined")
            current = current / part
            if _lexists(current):
                info = current.lstat()
                if _is_link_like(info):
                    raise ParityRepositoryError(
                        f"Managed path is a link or reparse point: {current.name}"
                    )
            resolved = current.resolve(strict=False)
            if resolved != root and not resolved.is_relative_to(root):
                raise ParityRepositoryError("Managed path is not confined to parity state")
        return current

    def _mkdir_managed(self, *parts: str) -> Path:
        current = self._prepare_root()
        consumed: list[str] = []
        for part in parts:
            consumed.append(part)
            current = self._managed_path(*consumed)
            current.mkdir(exist_ok=True)
            self._require_plain_directory(current, "Managed directory")
        return current

    @staticmethod
    def _require_plain_directory(path: Path, label: str) -> None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            raise FileNotFoundError(path) from None
        if _is_link_like(info) or not stat.S_ISDIR(info.st_mode):
            raise ParityRepositoryError(f"{label} is a link, reparse point, or non-directory")

    @staticmethod
    def _require_regular_file(path: Path, label: str) -> None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            raise FileNotFoundError(path) from None
        if _is_link_like(info) or not stat.S_ISREG(info.st_mode):
            raise ParityRepositoryError(f"{label} is a link, reparse point, or non-file")

    def _read_regular_bytes(self, path: Path, label: str) -> bytes:
        self._require_regular_file(path, label)
        return path.read_bytes()

    def _optional_regular_bytes(self, path: Path, label: str) -> bytes:
        if not _lexists(path):
            return b""
        return self._read_regular_bytes(path, label)


_RUN_FIELDS = {
    "schema_version",
    "run_id",
    "task_id",
    "status",
    "catalogue_version",
    "catalogue_hash",
    "manifest_path",
    "manifest_hash",
    "manifest_snapshot_path",
    "app_version",
    "created_at",
    "completed_at",
    "report_json_path",
    "report_markdown_path",
    "required_case_ids",
    "manual_items",
    "thresholds",
    "threshold_overrides",
    "source_fingerprints",
    "reference_fingerprints",
    "case_results",
    "warnings",
}


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


def _read_object(path: Path, fields: set[str]) -> dict[str, Any]:
    try:
        return _decode_object(path.read_bytes(), path.name, fields)
    except OSError as error:
        raise ParityRepositoryError(f"Cannot read parity evidence: {path.name}") from error


def _decode_object(
    raw: bytes,
    label: str,
    fields: set[str] | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ParityRepositoryError(f"Cannot decode parity evidence: {label}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
        raise ParityRepositoryError(f"Unsupported parity evidence: {label}")
    if fields is not None and set(payload) != fields:
        raise ParityRepositoryError(f"Unexpected fields in parity evidence: {label}")
    return payload


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


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
        "manifest_snapshot_path": run.manifest_snapshot_path,
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
        "threshold_overrides": [_threshold_override_payload(item) for item in run.threshold_overrides],
        "source_fingerprints": _fingerprints_payload(run.source_fingerprints),
        "reference_fingerprints": _fingerprints_payload(run.reference_fingerprints),
        "case_results": [_case_result_payload(item) for item in run.case_results],
        "warnings": list(redact_report_value(run.warnings)),
    }


def _run_from_payload(payload: Mapping[str, Any]) -> ParityRun:
    try:
        _require_exact_fields(payload, _RUN_FIELDS, "run envelope")
        status = _string(payload["status"], "status")
        if status not in _RUN_STATUSES:
            raise ValueError("Unknown run status")
        completed_at = payload["completed_at"]
        if completed_at is not None:
            completed_at = _nonempty_string(completed_at, "completed_at")
        if (status == "running") != (completed_at is None):
            raise ValueError("Run status and completion timestamp disagree")
        required_case_ids = _string_tuple(payload["required_case_ids"], "required_case_ids")
        _require_unique(required_case_ids, "required case IDs")
        manual_items = tuple(_manual_item_from_payload(item) for item in _array(payload["manual_items"], "manual_items"))
        _require_unique(tuple(item.item_id for item in manual_items), "manual item IDs")
        case_results = tuple(_case_result_from_payload(item) for item in _array(payload["case_results"], "case_results"))
        _require_unique(tuple(item.case_id for item in case_results), "case result IDs")
        overrides = tuple(
            _threshold_override_from_payload(item)
            for item in _array(payload["threshold_overrides"], "threshold_overrides")
        )
        _require_unique(
            tuple(f"{item.case_id}\0{item.threshold_id}" for item in overrides),
            "threshold overrides",
        )
        return ParityRun(
            run_id=_validate_run_id(_nonempty_string(payload["run_id"], "run_id")),
            task_id=_nonempty_string(payload["task_id"], "task_id"),
            status=status,  # type: ignore[arg-type]
            catalogue_version=_nonempty_string(payload["catalogue_version"], "catalogue_version"),
            catalogue_hash=_hash_string(payload["catalogue_hash"], "catalogue_hash"),
            manifest_path=_nonempty_string(payload["manifest_path"], "manifest_path"),
            manifest_hash=_hash_string(payload["manifest_hash"], "manifest_hash"),
            manifest_snapshot_path=_fixed_snapshot_path(payload["manifest_snapshot_path"]),
            app_version=_nonempty_string(payload["app_version"], "app_version"),
            created_at=_nonempty_string(payload["created_at"], "created_at"),
            completed_at=completed_at,
            report_json_path=_nonempty_string(payload["report_json_path"], "report_json_path"),
            report_markdown_path=_nonempty_string(payload["report_markdown_path"], "report_markdown_path"),
            required_case_ids=required_case_ids,
            manual_items=manual_items,
            thresholds=_thresholds_from_payload(payload["thresholds"]),
            threshold_overrides=overrides,
            source_fingerprints=_fingerprints_from_payload(payload["source_fingerprints"]),
            reference_fingerprints=_fingerprints_from_payload(payload["reference_fingerprints"]),
            case_results=case_results,
            warnings=_string_tuple(payload["warnings"], "warnings"),
        )
    except (KeyError, TypeError, ValueError, ParityRepositoryError) as error:
        if isinstance(error, ParityRepositoryError):
            raise
        raise ParityRepositoryError("Invalid parity run envelope") from error


def _manual_item_from_payload(value: Any) -> ManualItem:
    payload = _object(value, "manual item")
    _require_exact_fields(payload, {"item_id", "case_id", "prompt", "required"}, "manual item")
    required = payload["required"]
    if not isinstance(required, bool):
        raise ValueError("Manual item required flag must be boolean")
    return ManualItem(
        item_id=_nonempty_string(payload["item_id"], "manual item ID"),
        case_id=_nonempty_string(payload["case_id"], "manual case ID"),
        prompt=_nonempty_string(payload["prompt"], "manual prompt"),
        required=required,
    )


def _case_result_payload(result: CaseResult) -> dict[str, Any]:
    return dict(
        redact_report_value(
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
    )


def _case_result_from_payload(value: Any) -> CaseResult:
    payload = _object(value, "case result")
    _require_exact_fields(payload, {"case_id", "status", "checks"}, "case result")
    checks: list[CheckResult] = []
    for raw in _array(payload["checks"], "checks"):
        check = _object(raw, "check result")
        _require_exact_fields(
            check,
            {"check_id", "status", "message", "measurements"},
            "check result",
        )
        measurements = _object(check["measurements"], "measurements")
        checks.append(
            CheckResult(
                check_id=_nonempty_string(check["check_id"], "check_id"),
                status=_nonempty_string(check["status"], "check status"),  # type: ignore[arg-type]
                message=_string(check["message"], "check message"),
                measurements=measurements,
            )
        )
    _require_unique(tuple(item.check_id for item in checks), "check result IDs")
    return CaseResult(
        case_id=_nonempty_string(payload["case_id"], "case_id"),
        status=_nonempty_string(payload["status"], "case status"),  # type: ignore[arg-type]
        checks=tuple(checks),
    )


def _threshold_override_payload(item: ThresholdOverride) -> dict[str, Any]:
    return {
        "case_id": item.case_id,
        "threshold_id": item.threshold_id,
        "catalogue_value": _persistence_value(item.catalogue_value),
        "override_value": _persistence_value(item.override_value),
        "provenance": redact_report_value(item.provenance),
        "note": redact_report_value(item.note),
        "relaxation": item.relaxation,
    }


def _threshold_override_from_payload(value: Any) -> ThresholdOverride:
    payload = _object(value, "threshold override")
    fields = {
        "case_id",
        "threshold_id",
        "catalogue_value",
        "override_value",
        "provenance",
        "note",
        "relaxation",
    }
    _require_exact_fields(payload, fields, "threshold override")
    if not isinstance(payload["relaxation"], bool):
        raise ValueError("Threshold relaxation flag must be boolean")
    return ThresholdOverride(
        case_id=_nonempty_string(payload["case_id"], "override case_id"),
        threshold_id=_nonempty_string(payload["threshold_id"], "override threshold_id"),
        catalogue_value=_threshold_value(payload["catalogue_value"]),
        override_value=_threshold_value(payload["override_value"]),
        provenance=_nonempty_string(payload["provenance"], "override provenance"),
        note=_nonempty_string(payload["note"], "override note"),
        relaxation=payload["relaxation"],
    )


def _thresholds_from_payload(value: Any) -> dict[str, dict[str, object]]:
    payload = _object(value, "thresholds")
    result: dict[str, dict[str, object]] = {}
    for case_id, raw in payload.items():
        _nonempty_string(case_id, "threshold case ID")
        values = _object(raw, "case thresholds")
        result[case_id] = {
            _nonempty_string(key, "threshold ID"): _threshold_value(item)
            for key, item in values.items()
        }
    return result


def _threshold_value(value: Any) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Threshold values must be finite")
    if value is None or not isinstance(value, (bool, int, float, str)):
        raise ValueError("Threshold values must be JSON scalars")
    return value


def _persistence_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Parity evidence mapping keys must be strings")
            result[key] = _persistence_value(item)
        return result
    if isinstance(value, (set, frozenset)):
        normalized = [_persistence_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
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


def _fingerprints_from_payload(value: Any) -> dict[str, SourceFingerprint]:
    payload = _object(value, "fingerprints")
    result: dict[str, SourceFingerprint] = {}
    fields = {"kind", "sha256", "byte_size", "entry_count"}
    for key, raw in payload.items():
        _nonempty_string(key, "fingerprint ID")
        item = _object(raw, "fingerprint")
        _require_exact_fields(item, fields, "fingerprint")
        byte_size = item["byte_size"]
        entry_count = item["entry_count"]
        if (
            isinstance(byte_size, bool)
            or not isinstance(byte_size, int)
            or byte_size < 0
            or isinstance(entry_count, bool)
            or not isinstance(entry_count, int)
            or entry_count < 0
        ):
            raise ValueError("Fingerprint counts must be non-negative integers")
        result[key] = SourceFingerprint(
            kind=_nonempty_string(item["kind"], "fingerprint kind"),
            sha256=_hash_string(item["sha256"], "fingerprint hash"),
            byte_size=byte_size,
            entry_count=entry_count,
        )
    return result


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


def _manual_answer_from_payload(value: Mapping[str, Any]) -> ManualAnswer:
    _require_exact_fields(value, {"item_id", "accepted", "note", "answered_at"}, "manual answer")
    if not isinstance(value["accepted"], bool):
        raise ParityRepositoryError("Manual answer decision must be boolean")
    answer = ManualAnswer(
        item_id=_nonempty_string(value["item_id"], "manual answer ID"),
        accepted=value["accepted"],
        note=_string(value["note"], "manual answer note"),
        answered_at=_nonempty_string(value["answered_at"], "manual answer timestamp"),
    )
    _validate_manual_answer(answer)
    return answer


def _validate_manual_answer(answer: ManualAnswer) -> None:
    if not answer.item_id or not isinstance(answer.accepted, bool) or not answer.answered_at:
        raise ValueError("Manual answer is malformed")


def _acceptance_payload(acceptance: AcceptanceRecord) -> dict[str, str]:
    return dict(
        redact_report_value(
            {
                "note": acceptance.note,
                "accepted_at": acceptance.accepted_at,
                "catalogue_hash": acceptance.catalogue_hash,
                "manifest_hash": acceptance.manifest_hash,
                "run_revision": acceptance.run_revision,
                "manual_revision": acceptance.manual_revision,
                "input_revision": acceptance.input_revision,
                "report_revision": acceptance.report_revision,
            }
        )
    )


def _acceptance_intent_payload(acceptance: AcceptanceRecord) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "note": str(redact_report_value(acceptance.note)),
        "accepted_at": acceptance.accepted_at,
        "catalogue_hash": acceptance.catalogue_hash,
        "manifest_hash": acceptance.manifest_hash,
        "run_revision": acceptance.run_revision,
        "manual_revision": acceptance.manual_revision,
        "input_revision": acceptance.input_revision,
    }


def _acceptance_intent_from_payload(value: Mapping[str, Any]) -> AcceptanceRecord:
    fields = {
        "schema_version",
        "note",
        "accepted_at",
        "catalogue_hash",
        "manifest_hash",
        "run_revision",
        "manual_revision",
        "input_revision",
    }
    _require_exact_fields(value, fields, "acceptance intent")
    return AcceptanceRecord(
        note=_nonempty_string(value["note"], "acceptance note"),
        accepted_at=_nonempty_string(value["accepted_at"], "acceptance timestamp"),
        catalogue_hash=_hash_string(value["catalogue_hash"], "accepted catalogue hash"),
        manifest_hash=_hash_string(value["manifest_hash"], "accepted manifest hash"),
        run_revision=_hash_string(value["run_revision"], "accepted run revision"),
        manual_revision=_hash_string(value["manual_revision"], "accepted manual revision"),
        input_revision=_hash_string(value["input_revision"], "accepted input revision"),
    )


def _acceptance_from_payload(value: Mapping[str, Any]) -> AcceptanceRecord:
    fields = {
        "note",
        "accepted_at",
        "catalogue_hash",
        "manifest_hash",
        "run_revision",
        "manual_revision",
        "input_revision",
        "report_revision",
    }
    _require_exact_fields(value, fields, "acceptance")
    acceptance = AcceptanceRecord(
        note=_nonempty_string(value["note"], "acceptance note"),
        accepted_at=_nonempty_string(value["accepted_at"], "acceptance timestamp"),
        catalogue_hash=_hash_string(value["catalogue_hash"], "accepted catalogue hash"),
        manifest_hash=_hash_string(value["manifest_hash"], "accepted manifest hash"),
        run_revision=_hash_string(value["run_revision"], "accepted run revision"),
        manual_revision=_hash_string(value["manual_revision"], "accepted manual revision"),
        input_revision=_hash_string(value["input_revision"], "accepted input revision"),
        report_revision=_hash_string(value["report_revision"], "accepted report revision"),
    )
    _validate_acceptance(acceptance)
    return acceptance


def _validate_acceptance(value: AcceptanceRecord) -> None:
    if not value.note.strip() or not value.accepted_at:
        raise ValueError("Acceptance note and timestamp are required")
    for digest in (
        value.catalogue_hash,
        value.manifest_hash,
        value.run_revision,
        value.manual_revision,
        value.input_revision,
        value.report_revision,
    ):
        if not _SHA256.fullmatch(digest):
            raise ValueError("Acceptance revisions must be SHA-256 values")


def _require_exact_fields(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise ParityRepositoryError(f"Unexpected fields in {label}")


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object with string keys")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    result = _string(value, label)
    if not result:
        raise ValueError(f"{label} cannot be empty")
    return result


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    return tuple(_nonempty_string(item, label) for item in _array(value, label))


def _hash_string(value: Any, label: str) -> str:
    result = _nonempty_string(value, label)
    if not _SHA256.fullmatch(result):
        raise ValueError(f"{label} must be lowercase SHA-256")
    return result


def _require_unique(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {label}")


def _fixed_snapshot_path(value: Any) -> str:
    result = _nonempty_string(value, "manifest_snapshot_path")
    if result != "inputs/manifest.json":
        raise ValueError("Unexpected manifest snapshot path")
    return result


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id) or run_id in {".", ".."}:
        raise ValueError("Invalid parity run ID")
    return run_id


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fingerprint_selected_manifest(run: ParityRun) -> SourceFingerprint:
    try:
        source = fingerprint_source(Path(run.manifest_path))
    except (FileNotFoundError, OSError, UnsafePathError) as error:
        raise ImmutableRunError(
            "Selected manifest source is unavailable or unsafe"
        ) from error
    if source.kind != "file" or source.sha256 != run.manifest_hash:
        raise ImmutableRunError("Selected manifest source changed after the run")
    return source


def _absolute_path_prefixes(path: Path) -> tuple[Path, ...]:
    absolute = Path(path)
    if not absolute.is_absolute() or not absolute.anchor:
        raise ValueError("Parity state root must be absolute")
    current = Path(absolute.anchor)
    prefixes = [current]
    for part in absolute.parts[1:]:
        current = current / part
        prefixes.append(current)
    return tuple(prefixes)


def _lexists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _is_link_like(file_info: os.stat_result) -> bool:
    attributes = getattr(file_info, "st_file_attributes", 0)
    return stat.S_ISLNK(file_info.st_mode) or bool(
        _REPARSE_POINT_ATTRIBUTE and attributes & _REPARSE_POINT_ATTRIBUTE
    )
