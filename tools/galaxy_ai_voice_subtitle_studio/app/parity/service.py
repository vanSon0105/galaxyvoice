"""Deep facade for native parity inspection, execution, and acceptance."""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..common.cache import stable_digest
from ..common.diagnostics import redact_sensitive_text
from ..common.errors import TaskCancelledError
from ..runtime.jobs import (
    CANCELLED,
    DONE,
    FAILED,
    INTERRUPTED,
    TaskContext,
    TaskRecord,
    TaskRegistry,
)
from .corpus import inspect_corpus, inspect_manifest, parse_manifest_bytes
from .migration import MigrationDryRun, inspect_migration_source
from .models import (
    CaseResult,
    CheckResult,
    CorpusInspection,
    ParityCase,
    ParityCatalogue,
    ParityFixtureManifest,
    SourceFingerprint,
)
from .reports import render_reports
from .repository import (
    AcceptanceRecord,
    ImmutableRunError,
    ManualAnswer,
    ManualItem,
    ParityRepository,
    ParityRepositoryError,
    ParityRun,
    RunStatus,
    ThresholdOverride,
)
from .security import resolve_approved_path
from .validators import DefaultMediaProbe, validate_case


PARITY_TASK_KIND = "native-parity-validation"
PARITY_RECOVERY_ROUTE = "/settings/parity"
_UPPER_BOUND_THRESHOLDS = frozenset(
    {
        "duration_absolute_ms",
        "duration_relative_ratio",
        "subtitle_timing_tolerance_ms",
        "loudness_tolerance_lu",
        "reference_performance_ratio",
        "interaction_p95_ms",
        "cpu_cancellation_seconds",
        "accelerator_cancellation_seconds",
    }
)


class ParityNotReadyError(RuntimeError):
    """Raised when evidence does not satisfy the local acceptance gate."""


@dataclass(frozen=True)
class ThresholdOverrideRequest:
    case_id: str
    threshold_id: str
    value: object
    provenance: str
    note: str


@dataclass(frozen=True)
class StartParityRun:
    manifest_path: Path
    approved_roots: tuple[Path, ...]
    app_version: str
    measurements_by_case: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    threshold_overrides: tuple[ThresholdOverrideRequest, ...] = ()
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
        object.__setattr__(self, "threshold_overrides", tuple(self.threshold_overrides))
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
        manifest_bytes = manifest_path.read_bytes()
        manifest = parse_manifest_bytes(manifest_bytes)
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        effective_thresholds, overrides = _resolve_requested_overrides(
            self.catalogue,
            request.threshold_overrides,
        )
        run_id = uuid.uuid4().hex
        task = self.task_registry.create(
            PARITY_TASK_KIND,
            run_id=run_id,
            resource_keys=("cpu", "disk"),
            recovery_route=PARITY_RECOVERY_ROUTE,
        )
        run = ParityRun(
            run_id=run_id,
            task_id=task.task_id,
            status="running",
            catalogue_version=self.catalogue.version,
            catalogue_hash=catalogue_digest(self.catalogue),
            manifest_path=str(manifest_path),
            manifest_hash=manifest_hash,
            manifest_snapshot_path="inputs/manifest.json",
            app_version=request.app_version,
            created_at=_now(),
            report_json_path=f"reports/{run_id}/current.json",
            report_markdown_path=f"reports/{run_id}/current.md",
            required_case_ids=tuple(
                case.case_id for case in self.catalogue.cases if case.required
            ),
            manual_items=_manual_contract(self.catalogue),
            thresholds=effective_thresholds,
            threshold_overrides=overrides,
            source_fingerprints=request.source_fingerprints,
            reference_fingerprints=request.reference_fingerprints,
        )
        try:
            self.repository.create_run(run, manifest_bytes=manifest_bytes)
        except Exception as error:
            self.task_registry.finish(task.task_id, status=FAILED, error=str(error))
            raise
        try:
            self.task_registry.submit(
                task,
                lambda context: self._execute_run(context, request, run_id, manifest),
                lambda completed_run_id: {"run_id": completed_run_id},
            )
        except Exception as error:
            self.task_registry.finish(task.task_id, status=FAILED, error=str(error))
            self._terminalize_submit_failure(run_id, error)
            raise
        return task

    def list_runs(self) -> tuple[ParityRun, ...]:
        return tuple(self._reconcile_run(run) for run in self.repository.list_runs())

    def get_run(self, run_id: str) -> ParityRun | None:
        run = self.repository.get_run(run_id)
        return self._reconcile_run(run) if run is not None else None

    def read_report(self, run_id: str, report_format: str) -> bytes:
        return self.repository.read_report(run_id, report_format)

    def ready_for_acceptance(self, run_id: str) -> bool:
        try:
            snapshot = self.repository.acceptance_snapshot(run_id)
            run = snapshot.run
            if run.acceptance is not None:
                return False
            self._assert_ready(run, acceptance_note="readiness probe")
        except (
            FileNotFoundError,
            ImmutableRunError,
            ParityNotReadyError,
            ParityRepositoryError,
            ValueError,
        ):
            return False
        task = self.task_registry.get(run.task_id)
        return (
            task is not None
            and task.kind == PARITY_TASK_KIND
            and task.run_id == run.run_id
            and task.status == DONE
        )

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
        except (ImmutableRunError, ParityRepositoryError, ValueError) as error:
            raise ParityNotReadyError(str(error)) from error
        return self._write_reports(updated)

    def accept_run(self, run_id: str, *, note: str) -> ParityRun:
        if not note.strip():
            raise ParityNotReadyError("Final acceptance requires a note")
        self._require_run(run_id)
        try:
            snapshot = self.repository.acceptance_snapshot(run_id)
        except FileNotFoundError as error:
            raise KeyError(run_id) from error
        except (ImmutableRunError, ParityRepositoryError, ValueError) as error:
            raise ParityNotReadyError(str(error)) from error
        run = snapshot.run
        if run.acceptance is not None:
            raise ParityNotReadyError("Parity run is already accepted")
        if run.status != "completed":
            raise ParityNotReadyError(
                f"Parity run status {run.status} cannot be accepted"
            )
        self._assert_ready(run, acceptance_note=note)
        acceptance = AcceptanceRecord(
            note=note.strip(),
            accepted_at=_now(),
            catalogue_hash=run.catalogue_hash,
            manifest_hash=run.manifest_hash,
        )

        def commit_with_task_guard(task: TaskRecord) -> ParityRun:
            if task.kind != PARITY_TASK_KIND or task.run_id != run.run_id:
                raise ParityNotReadyError("Matching parity task must be terminal done")
            if task.status != DONE:
                raise ParityNotReadyError("Parity task must be terminal done")
            return self.repository.commit_acceptance(snapshot, acceptance)

        try:
            accepted = self.task_registry.run_with_task_guard(
                run.task_id,
                commit_with_task_guard,
            )
        except KeyError as error:
            raise ParityNotReadyError("Matching parity task must be terminal done") from error
        except (ImmutableRunError, ParityRepositoryError, ValueError) as error:
            raise ParityNotReadyError(str(error)) from error
        return self._write_reports(accepted)

    def _execute_run(
        self,
        context: TaskContext,
        request: StartParityRun,
        run_id: str,
        manifest: ParityFixtureManifest,
    ) -> str:
        case_results: list[CaseResult] = []
        warnings: list[str] = []
        try:
            context.report("Đang kiểm tra corpus đối chiếu.", progress=0.0)
            context.check_cancelled()
            run = self.repository.get_run(run_id)
            if run is None:
                raise RuntimeError("Parity run snapshot is unavailable")
            corpus = inspect_manifest(
                manifest,
                approved_roots=request.approved_roots,
                asset_root=Path(run.manifest_path).parent,
            )
            probe = DefaultMediaProbe()
            total = max(1, len(self.catalogue.cases))
            relaxed_cases = {
                item.case_id for item in run.threshold_overrides if item.relaxation
            }
            for index, catalogue_case in enumerate(self.catalogue.cases):
                context.check_cancelled()
                context.report(
                    f"Đang đối chiếu {catalogue_case.title}.",
                    progress=index / total,
                )
                assets = {
                    role: inspection.path
                    for role in catalogue_case.fixture_roles
                    if (inspection := corpus.assets_by_role.get(role)) is not None
                    and inspection.status == "ready"
                    and inspection.path is not None
                }
                case = replace(
                    catalogue_case,
                    thresholds=run.thresholds[catalogue_case.case_id],
                )
                try:
                    kwargs: dict[str, Any] = {}
                    if case.case_id in relaxed_cases:
                        kwargs["allow_threshold_relaxation"] = True
                    result = validate_case(
                        case,
                        assets,
                        probe=probe,
                        measurements=request.measurements_by_case.get(case.case_id, {}),
                        **kwargs,
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
                redact_sensitive_text(f"Run failed: {type(error).__name__}: {error}")
            )
            self._finish_if_running(run_id, "failed", case_results, warnings)
            raise

    def _terminalize_submit_failure(self, run_id: str, error: Exception) -> None:
        run = self.repository.get_run(run_id)
        if run is None or run.status != "running":
            return
        try:
            failed = self.repository.finish_run(
                run_id,
                status="failed",
                case_results=run.case_results,
                warnings=(
                    redact_sensitive_text(
                        f"Task submission failed: {type(error).__name__}: {error}"
                    ),
                ),
                completed_at=_now(),
            )
            self._write_reports(failed)
        except Exception:
            # The original submission error remains the caller-visible failure.
            pass

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
        return self._write_reports(run)

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

    def _write_reports(self, run: ParityRun) -> ParityRun:
        revision_input = render_reports(
            replace(run, report_json_path="", report_markdown_path="")
        )
        revision = hashlib.sha256(
            revision_input.json_bytes + b"\0" + revision_input.markdown.encode("utf-8")
        ).hexdigest()
        json_path, markdown_path = self.repository.report_revision_paths(
            run.run_id,
            revision,
        )
        published = replace(
            run,
            report_json_path=json_path,
            report_markdown_path=markdown_path,
        )
        rendered = render_reports(published)
        self.repository.write_reports(
            run.run_id,
            rendered.json_bytes,
            rendered.markdown,
            revision=revision,
        )
        return published

    def _require_run(self, run_id: str) -> ParityRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _reconcile_run(self, run: ParityRun) -> ParityRun:
        if run.status != "running":
            return run
        task = self.task_registry.get(run.task_id)
        status_by_task: dict[str, RunStatus] = {
            CANCELLED: "cancelled",
            INTERRUPTED: "interrupted",
            FAILED: "failed",
        }
        status = status_by_task.get(task.status) if task is not None else None
        if status is None:
            return run
        return self._finish_run(
            run.run_id,
            status,
            list(run.case_results),
            list(run.warnings),
        )

    def _assert_ready(self, run: ParityRun, *, acceptance_note: str) -> None:
        if run.status != "completed":
            raise ParityNotReadyError(
                f"Parity run status {run.status} cannot be accepted"
            )
        current_catalogue_hash = catalogue_digest(self.catalogue)
        if (
            run.catalogue_version != self.catalogue.version
            or run.catalogue_hash != current_catalogue_hash
        ):
            raise ParityNotReadyError("Parity catalogue hash changed after the run")
        _assert_catalogue_contract(self.catalogue, run)
        _, expected_overrides = _resolve_evidence_overrides(
            self.catalogue,
            run.threshold_overrides,
        )
        if expected_overrides != run.threshold_overrides:
            raise ParityNotReadyError("Threshold override evidence is malformed")
        expected_thresholds, _ = _resolve_evidence_overrides(
            self.catalogue,
            run.threshold_overrides,
        )
        if _plain_thresholds(run.thresholds) != expected_thresholds:
            raise ParityNotReadyError("Effective threshold evidence changed")
        if any(item.relaxation for item in run.threshold_overrides) and not acceptance_note.strip():
            raise ParityNotReadyError(
                "Relaxed threshold overrides require an explicit manual acceptance note"
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


def _assert_catalogue_contract(catalogue: ParityCatalogue, run: ParityRun) -> None:
    case_ids = tuple(case.case_id for case in catalogue.cases)
    if len(case_ids) != len(set(case_ids)):
        raise ParityNotReadyError("Current catalogue contains duplicate case IDs")
    expected_required = tuple(case.case_id for case in catalogue.cases if case.required)
    if run.required_case_ids != expected_required:
        raise ParityNotReadyError("Required case contract does not match the catalogue")
    expected_manual = _manual_contract(catalogue)
    if run.manual_items != expected_manual:
        raise ParityNotReadyError("Required manual contract does not match the catalogue")
    result_ids = tuple(result.case_id for result in run.case_results)
    if result_ids != case_ids:
        raise ParityNotReadyError("Case evidence is missing, duplicate, extra, or out of order")
    results = dict(zip(result_ids, run.case_results, strict=True))
    for case in catalogue.cases:
        if len(case.checks) != len(set(case.checks)):
            raise ParityNotReadyError(f"Catalogue case {case.case_id} has duplicate checks")
        result = results[case.case_id]
        check_ids = tuple(check.check_id for check in result.checks)
        if check_ids != case.checks:
            raise ParityNotReadyError(f"Case {case.case_id} check contract does not match")
        effective_status = _case_status_from_checks(result)
        if result.status != effective_status:
            raise ParityNotReadyError(
                f"Case {case.case_id} aggregate status is malformed ({effective_status})"
            )
        if case.required and effective_status != "pass":
            raise ParityNotReadyError(
                f"Required case {case.case_id} is {effective_status}"
            )
    expected_item_ids = {item.item_id for item in expected_manual}
    answer_ids = set(run.manual_answers)
    if not answer_ids.issubset(expected_item_ids):
        raise ParityNotReadyError("Manual evidence contains extra item IDs")
    for item in expected_manual:
        answer = run.manual_answers.get(item.item_id)
        if item.required and (answer is None or not answer.accepted):
            raise ParityNotReadyError(
                f"Required manual item {item.item_id} is not accepted"
            )


def _manual_contract(catalogue: ParityCatalogue) -> tuple[ManualItem, ...]:
    return tuple(
        ManualItem(
            item_id=f"{case.case_id}.manual.{index}",
            case_id=case.case_id,
            prompt=prompt,
            required=case.required,
        )
        for case in catalogue.cases
        for index, prompt in enumerate(case.manual_prompts, start=1)
    )


def _resolve_requested_overrides(
    catalogue: ParityCatalogue,
    requested: tuple[ThresholdOverrideRequest, ...],
) -> tuple[dict[str, dict[str, object]], tuple[ThresholdOverride, ...]]:
    evidence: list[ThresholdOverride] = []
    seen: set[tuple[str, str]] = set()
    cases = {case.case_id: case for case in catalogue.cases}
    effective = {case.case_id: dict(case.thresholds) for case in catalogue.cases}
    for item in requested:
        key = (item.case_id, item.threshold_id)
        if key in seen:
            raise ValueError("Duplicate threshold override")
        seen.add(key)
        case = cases.get(item.case_id)
        if case is None or item.threshold_id not in case.thresholds:
            raise ValueError("Threshold override does not match the catalogue")
        if not item.provenance.strip() or not item.note.strip():
            raise ValueError("Threshold override provenance and note are required")
        value = _threshold_scalar(item.value)
        catalogue_value = case.thresholds[item.threshold_id]
        if value == catalogue_value:
            raise ValueError("Threshold override must change the catalogue value")
        relaxation = _is_relaxation(item.threshold_id, catalogue_value, value)
        evidence.append(
            ThresholdOverride(
                case_id=item.case_id,
                threshold_id=item.threshold_id,
                catalogue_value=catalogue_value,
                override_value=value,
                provenance=item.provenance.strip(),
                note=item.note.strip(),
                relaxation=relaxation,
            )
        )
        effective[item.case_id][item.threshold_id] = value
    return effective, tuple(evidence)


def _resolve_evidence_overrides(
    catalogue: ParityCatalogue,
    evidence: tuple[ThresholdOverride, ...],
) -> tuple[dict[str, dict[str, object]], tuple[ThresholdOverride, ...]]:
    requested = tuple(
        ThresholdOverrideRequest(
            case_id=item.case_id,
            threshold_id=item.threshold_id,
            value=item.override_value,
            provenance=item.provenance,
            note=item.note,
        )
        for item in evidence
    )
    return _resolve_requested_overrides(catalogue, requested)


def _is_relaxation(threshold_id: str, catalogue_value: object, value: object) -> bool:
    if (
        threshold_id in _UPPER_BOUND_THRESHOLDS
        and _finite_number(catalogue_value)
        and _finite_number(value)
    ):
        return float(value) > float(catalogue_value)
    return value != catalogue_value


def _threshold_scalar(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Threshold override must be finite")
    if value is None or not isinstance(value, (bool, int, float, str)):
        raise ValueError("Threshold override must be a JSON scalar")
    return value


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _plain_thresholds(
    value: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    return {case_id: dict(thresholds) for case_id, thresholds in value.items()}


def _case_status_from_checks(result: CaseResult) -> str:
    statuses = {check.status for check in result.checks}
    for status in ("fail", "blocked", "manual_pending", "pass"):
        if status in statuses:
            return status
    return "not_applicable"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
