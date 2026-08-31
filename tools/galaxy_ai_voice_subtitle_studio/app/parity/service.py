"""Deep facade for native parity inspection, execution, and acceptance."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..common.cache import file_digest, stable_digest
from ..common.diagnostics import redact_sensitive_text
from ..common.errors import TaskCancelledError
from ..runtime.jobs import CANCELLED, FAILED, INTERRUPTED, TaskContext, TaskRecord, TaskRegistry
from .corpus import inspect_corpus
from .migration import MigrationDryRun, inspect_migration_source
from .models import (
    CaseResult,
    CheckResult,
    CorpusInspection,
    ParityCatalogue,
    SourceFingerprint,
)
from .reports import render_reports
from .repository import (
    AcceptanceRecord,
    ImmutableRunError,
    ManualAnswer,
    ManualItem,
    ParityRepository,
    ParityRun,
    RunStatus,
)
from .security import resolve_approved_path
from .validators import DefaultMediaProbe, validate_case


PARITY_TASK_KIND = "native-parity-validation"
PARITY_RECOVERY_ROUTE = "/settings/parity"


class ParityNotReadyError(RuntimeError):
    """Raised when evidence does not satisfy the local acceptance gate."""


@dataclass(frozen=True)
class StartParityRun:
    manifest_path: Path
    approved_roots: tuple[Path, ...]
    app_version: str
    measurements_by_case: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    source_fingerprints: Mapping[str, SourceFingerprint] = field(default_factory=dict)
    reference_fingerprints: Mapping[str, SourceFingerprint] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_path", Path(self.manifest_path))
        object.__setattr__(
            self,
            "approved_roots",
            tuple(Path(item) for item in self.approved_roots),
        )
        object.__setattr__(
            self,
            "measurements_by_case",
            MappingProxyType(
                {
                    str(case_id): MappingProxyType(dict(values))
                    for case_id, values in self.measurements_by_case.items()
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


class ParityService:
    def __init__(
        self,
        catalogue: ParityCatalogue,
        repository: ParityRepository,
        task_registry: TaskRegistry,
    ) -> None:
        self.catalogue = catalogue
        self.repository = repository
        self.task_registry = task_registry

    def list_catalogue(self) -> ParityCatalogue:
        return self.catalogue

    def inspect_corpus(
        self,
        manifest_path: Path,
        *,
        approved_roots: Sequence[Path],
    ) -> CorpusInspection:
        return inspect_corpus(manifest_path, approved_roots=approved_roots)

    def inspect_migration(
        self,
        source: Path,
        *,
        approved_roots: Sequence[Path],
        copied_source_confirmed: bool,
        sandbox_root: Path | None = None,
    ) -> MigrationDryRun:
        return inspect_migration_source(
            source,
            approved_roots=approved_roots,
            copied_source_confirmed=copied_source_confirmed,
            sandbox_root=sandbox_root,
        )

    def start_run(self, request: StartParityRun) -> TaskRecord:
        manifest_path = resolve_approved_path(request.manifest_path, request.approved_roots)
        manifest_hash = file_digest(manifest_path)
        run_id = uuid.uuid4().hex
        task = self.task_registry.create(
            PARITY_TASK_KIND,
            resource_keys=("cpu", "disk"),
            recovery_route=PARITY_RECOVERY_ROUTE,
        )
        task.run_id = run_id
        run = ParityRun(
            run_id=run_id,
            task_id=task.task_id,
            status="running",
            catalogue_version=self.catalogue.version,
            catalogue_hash=catalogue_digest(self.catalogue),
            manifest_path=str(manifest_path),
            manifest_hash=manifest_hash,
            app_version=request.app_version,
            created_at=_now(),
            report_json_path=f"reports/{run_id}.json",
            report_markdown_path=f"reports/{run_id}.md",
            required_case_ids=tuple(
                case.case_id for case in self.catalogue.cases if case.required
            ),
            manual_items=tuple(
                ManualItem(
                    item_id=f"{case.case_id}.manual.{index}",
                    case_id=case.case_id,
                    prompt=prompt,
                    required=case.required,
                )
                for case in self.catalogue.cases
                for index, prompt in enumerate(case.manual_prompts, start=1)
            ),
            thresholds={case.case_id: dict(case.thresholds) for case in self.catalogue.cases},
            source_fingerprints=request.source_fingerprints,
            reference_fingerprints=request.reference_fingerprints,
        )
        try:
            self.repository.create_run(run)
        except Exception as error:
            self.task_registry.finish(task.task_id, status=FAILED, error=str(error))
            raise
        self.task_registry.submit(
            task,
            lambda context: self._execute_run(context, request, run_id),
            lambda completed_run_id: {"run_id": completed_run_id},
        )
        return task

    def list_runs(self) -> tuple[ParityRun, ...]:
        return tuple(self._reconcile_run(run) for run in self.repository.list_runs())

    def get_run(self, run_id: str) -> ParityRun | None:
        run = self.repository.get_run(run_id)
        return self._reconcile_run(run) if run is not None else None

    def read_report(self, run_id: str, report_format: str) -> bytes:
        return self.repository.read_report(run_id, report_format)

    def record_manual_item(
        self,
        run_id: str,
        item_id: str,
        *,
        accepted: bool,
        note: str,
    ) -> ParityRun:
        if not isinstance(accepted, bool):
            raise ValueError("Manual acceptance must be a boolean")
        run = self._require_run(run_id)
        if run.acceptance is not None:
            raise ParityNotReadyError("Manual evidence cannot change an accepted run")
        try:
            updated = self.repository.record_manual_answer(
                run_id,
                ManualAnswer(
                    item_id=item_id,
                    accepted=accepted,
                    note=note,
                    answered_at=_now(),
                ),
            )
        except ImmutableRunError as error:
            raise ParityNotReadyError(str(error)) from error
        self._write_reports(updated)
        return updated

    def accept_run(self, run_id: str, *, note: str) -> ParityRun:
        run = self._require_run(run_id)
        if run.acceptance is not None:
            raise ParityNotReadyError("Parity run is already accepted")
        if not note.strip():
            raise ParityNotReadyError("Final acceptance requires a note")
        self._assert_ready(run)
        acceptance = AcceptanceRecord(
            note=note.strip(),
            accepted_at=_now(),
            catalogue_hash=run.catalogue_hash,
            manifest_hash=run.manifest_hash,
        )
        try:
            accepted = self.repository.record_acceptance(run_id, acceptance)
        except ImmutableRunError as error:
            raise ParityNotReadyError(str(error)) from error
        self._write_reports(accepted)
        return accepted

    def _execute_run(
        self,
        context: TaskContext,
        request: StartParityRun,
        run_id: str,
    ) -> str:
        case_results: list[CaseResult] = []
        warnings: list[str] = []
        try:
            context.report("Đang kiểm tra corpus đối chiếu.", progress=0.0)
            context.check_cancelled()
            corpus = inspect_corpus(
                request.manifest_path,
                approved_roots=request.approved_roots,
            )
            probe = DefaultMediaProbe()
            total = max(1, len(self.catalogue.cases))
            for index, case in enumerate(self.catalogue.cases):
                context.check_cancelled()
                context.report(
                    f"Đang đối chiếu {case.title}.",
                    progress=index / total,
                )
                assets = {
                    role: inspection.path
                    for role in case.fixture_roles
                    if (inspection := corpus.assets_by_role.get(role)) is not None
                    and inspection.status == "ready"
                    and inspection.path is not None
                }
                try:
                    result = validate_case(
                        case,
                        assets,
                        probe=probe,
                        measurements=request.measurements_by_case.get(case.case_id, {}),
                    )
                except TaskCancelledError:
                    raise
                except Exception as error:
                    result = CaseResult(
                        case_id=case.case_id,
                        status="fail",
                        checks=(
                            CheckResult(
                                check_id="case_execution",
                                status="fail",
                                message=redact_sensitive_text(
                                    f"Case execution failed: {type(error).__name__}: {error}"
                                ),
                            ),
                        ),
                    )
                case_results.append(result)
                self.repository.record_case_result(run_id, result)
                context.save_checkpoint(
                    {
                        "run_id": run_id,
                        "completed_case_ids": [item.case_id for item in case_results],
                    }
                )
                context.check_cancelled()
            self._finish_run(run_id, "completed", case_results, warnings)
            context.report("Đã hoàn tất đối chiếu native.", progress=1.0)
            return run_id
        except TaskCancelledError:
            self._finish_if_running(run_id, "cancelled", case_results, warnings)
            raise
        except Exception as error:
            warnings.append(
                redact_sensitive_text(
                    f"Run failed: {type(error).__name__}: {error}"
                )
            )
            self._finish_if_running(run_id, "failed", case_results, warnings)
            raise

    def _finish_run(
        self,
        run_id: str,
        status: RunStatus,
        case_results: list[CaseResult],
        warnings: list[str],
    ) -> ParityRun:
        run = self.repository.finish_run(
            run_id,
            status=status,
            case_results=tuple(case_results),
            warnings=tuple(warnings),
            completed_at=_now(),
        )
        self._write_reports(run)
        return run

    def _finish_if_running(
        self,
        run_id: str,
        status: RunStatus,
        case_results: list[CaseResult],
        warnings: list[str],
    ) -> None:
        current = self.repository.get_run(run_id)
        if current is not None and current.status == "running":
            self._finish_run(run_id, status, case_results, warnings)

    def _write_reports(self, run: ParityRun) -> None:
        rendered = render_reports(run)
        self.repository.write_reports(run.run_id, rendered.json_bytes, rendered.markdown)

    def _require_run(self, run_id: str) -> ParityRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _reconcile_run(self, run: ParityRun) -> ParityRun:
        if run.status != "running":
            return run
        task = self.task_registry.get(run.task_id)
        status_by_task = {
            CANCELLED: "cancelled",
            INTERRUPTED: "interrupted",
            FAILED: "failed",
        }
        status = status_by_task.get(task.status) if task is not None else None
        if status is None:
            return run
        return self._finish_run(
            run.run_id,
            status,  # type: ignore[arg-type]
            list(run.case_results),
            list(run.warnings),
        )

    def _assert_ready(self, run: ParityRun) -> None:
        if run.status != "completed":
            raise ParityNotReadyError(
                f"Parity run status {run.status} cannot be accepted"
            )
        task = self.task_registry.get(run.task_id)
        if task is not None and task.status in {CANCELLED, INTERRUPTED, FAILED}:
            raise ParityNotReadyError(
                f"Parity task status {task.status} cannot be accepted"
            )
        current_catalogue_hash = catalogue_digest(self.catalogue)
        if (
            run.catalogue_version != self.catalogue.version
            or run.catalogue_hash != current_catalogue_hash
        ):
            raise ParityNotReadyError("Parity catalogue hash changed after the run")
        try:
            current_manifest_hash = file_digest(Path(run.manifest_path))
        except OSError as error:
            raise ParityNotReadyError("Parity manifest is unavailable") from error
        if current_manifest_hash != run.manifest_hash:
            raise ParityNotReadyError("Parity manifest hash changed after the run")
        results = {result.case_id: result for result in run.case_results}
        for case_id in run.required_case_ids:
            result = results.get(case_id)
            if result is None:
                raise ParityNotReadyError(f"Required case {case_id} is incomplete")
            effective_status = _case_status_from_checks(result)
            if effective_status != "pass":
                raise ParityNotReadyError(
                    f"Required case {case_id} is {effective_status}"
                )
        for item in run.manual_items:
            if not item.required:
                continue
            answer = run.manual_answers.get(item.item_id)
            if answer is None or not answer.accepted:
                raise ParityNotReadyError(
                    f"Required manual item {item.item_id} is not accepted"
                )


def catalogue_digest(catalogue: ParityCatalogue) -> str:
    return stable_digest(
        {
            "version": catalogue.version,
            "cases": [
                {
                    "case_id": case.case_id,
                    "area": case.area,
                    "title": case.title,
                    "required": case.required,
                    "fixture_roles": list(case.fixture_roles),
                    "checks": list(case.checks),
                    "manual_prompts": list(case.manual_prompts),
                    "thresholds": dict(case.thresholds),
                }
                for case in catalogue.cases
            ],
        }
    )


def _case_status_from_checks(result: CaseResult) -> str:
    statuses = {check.status for check in result.checks}
    for status in ("fail", "blocked", "manual_pending", "pass"):
        if status in statuses:
            return status
    return "not_applicable"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
