from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.common.cache import file_digest
from app.parity import CaseResult, CheckResult, ParityCase, ParityCatalogue
from app.parity.repository import ManualItem, ParityRepository, ParityRun
from app.parity.service import (
    ParityNotReadyError,
    ParityService,
    StartParityRun,
    catalogue_digest,
)
from app.runtime.jobs import CANCELLED, DONE, INTERRUPTED, TaskRegistry


def _catalogue(*, case_count: int = 1, version: str = "v1") -> ParityCatalogue:
    cases = tuple(
        ParityCase(
            case_id=f"case.{index}",
            area="studio",
            title=f"Case {index}",
            required=True,
            checks=("output_format",),
            manual_prompts=(f"Confirm case {index}",),
            thresholds={"duration_absolute_ms": 250},
        )
        for index in range(case_count)
    )
    return ParityCatalogue(version=version, cases=cases)


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_id": "test-corpus",
                "created_at": "2026-08-30T00:00:00Z",
                "cases": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _start(
    service: ParityService,
    manifest: Path,
    *,
    measurements: dict[str, dict[str, object]] | None = None,
):
    return service.start_run(
        StartParityRun(
            manifest_path=manifest,
            approved_roots=(manifest.parent,),
            app_version="15.0",
            measurements_by_case=measurements or {},
        )
    )


def _join(task) -> None:
    assert task.thread is not None
    task.thread.join(timeout=5)
    assert not task.thread.is_alive()


def test_start_run_uses_task_registry_contract_and_serializes_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.parity.service.validate_case",
        lambda case, assets, *, probe, measurements: CaseResult(
            case.case_id,
            "pass",
            (CheckResult("output_format", "pass", "ok"),),
        ),
    )
    registry = TaskRegistry()
    service = ParityService(_catalogue(), ParityRepository(tmp_path / "state"), registry)

    task = _start(service, _manifest(tmp_path))
    _join(task)

    assert task.kind == "native-parity-validation"
    assert task.resource_keys == ("cpu", "disk")
    assert task.recovery_route == "/settings/parity"
    assert task.status == DONE
    assert task.result_payload == {"run_id": task.run_id}
    assert service.get_run(task.run_id).status == "completed"  # type: ignore[union-attr]


def test_start_run_persistence_failure_does_not_leave_active_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = TaskRegistry()
    repository = ParityRepository(tmp_path / "state")
    service = ParityService(_catalogue(), repository, registry)
    monkeypatch.setattr(
        repository,
        "create_run",
        lambda _run: (_ for _ in ()).throw(PermissionError("state is locked")),
    )

    with pytest.raises(PermissionError, match="state is locked"):
        _start(service, _manifest(tmp_path))

    assert registry.running_count() == 0
    assert registry.snapshot()[0]["status"] == "failed"


def test_independent_case_exception_is_failed_and_later_cases_continue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    def validate(case, assets, *, probe, measurements):
        called.append(case.case_id)
        if case.case_id == "case.0":
            raise RuntimeError("Authorization: Bearer secret-token")
        return CaseResult(
            case.case_id,
            "pass",
            (CheckResult("output_format", "pass", "ok"),),
        )

    monkeypatch.setattr("app.parity.service.validate_case", validate)
    service = ParityService(
        _catalogue(case_count=2),
        ParityRepository(tmp_path / "state"),
        TaskRegistry(),
    )

    task = _start(service, _manifest(tmp_path))
    _join(task)
    run = service.get_run(task.run_id)

    assert called == ["case.0", "case.1"]
    assert run is not None
    assert [item.status for item in run.case_results] == ["fail", "pass"]
    assert "secret-token" not in run.case_results[0].checks[0].message


def test_cancellation_persists_partial_evidence_and_cannot_be_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def validate(case, assets, *, probe, measurements):
        entered.set()
        release.wait(timeout=5)
        return CaseResult(
            case.case_id,
            "pass",
            (CheckResult("output_format", "pass", "ok"),),
        )

    monkeypatch.setattr("app.parity.service.validate_case", validate)
    registry = TaskRegistry()
    service = ParityService(
        _catalogue(case_count=2),
        ParityRepository(tmp_path / "state"),
        registry,
    )
    task = _start(service, _manifest(tmp_path))
    assert entered.wait(timeout=5)

    assert registry.cancel(task.task_id)
    release.set()
    _join(task)
    run = service.get_run(task.run_id)

    assert task.status == CANCELLED
    assert run is not None
    assert run.status == "cancelled"
    assert len(run.case_results) == 1
    with pytest.raises(ParityNotReadyError, match="cancelled"):
        service.accept_run(run.run_id, note="reviewed")


def test_acceptance_recomputes_readiness_hashes_and_manual_answers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.parity.service.validate_case",
        lambda case, assets, *, probe, measurements: CaseResult(
            case.case_id,
            "pass",
            (CheckResult("output_format", "pass", "ok"),),
        ),
    )
    manifest = _manifest(tmp_path)
    service = ParityService(
        _catalogue(),
        ParityRepository(tmp_path / "state"),
        TaskRegistry(),
    )
    task = _start(service, manifest)
    _join(task)

    with pytest.raises(ParityNotReadyError, match="manual"):
        service.accept_run(task.run_id, note="reviewed")

    service.record_manual_item(
        task.run_id,
        "case.0.manual.1",
        accepted=True,
        note="listened",
    )
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ParityNotReadyError, match="manifest"):
        service.accept_run(task.run_id, note="reviewed")


def test_acceptance_rejects_blocked_or_changed_catalogue_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result_status = "blocked"

    def validate(case, assets, *, probe, measurements):
        return CaseResult(
            case.case_id,
            result_status,
            (CheckResult("output_format", result_status, result_status),),
        )

    monkeypatch.setattr("app.parity.service.validate_case", validate)
    repository = ParityRepository(tmp_path / "state")
    service = ParityService(_catalogue(), repository, TaskRegistry())
    manifest = _manifest(tmp_path)
    task = _start(service, manifest)
    _join(task)
    service.record_manual_item(
        task.run_id,
        "case.0.manual.1",
        accepted=True,
        note="reviewed",
    )

    with pytest.raises(ParityNotReadyError, match="blocked"):
        service.accept_run(task.run_id, note="reviewed")

    changed_service = ParityService(
        _catalogue(version="v2"),
        repository,
        TaskRegistry(),
    )
    with pytest.raises(ParityNotReadyError, match="catalogue"):
        changed_service.accept_run(task.run_id, note="reviewed")


def test_acceptance_is_final_and_regenerates_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.parity.service.validate_case",
        lambda case, assets, *, probe, measurements: CaseResult(
            case.case_id,
            "pass",
            (CheckResult("output_format", "pass", "ok"),),
        ),
    )
    service = ParityService(
        _catalogue(),
        ParityRepository(tmp_path / "state"),
        TaskRegistry(),
    )
    task = _start(service, _manifest(tmp_path))
    _join(task)
    service.record_manual_item(
        task.run_id,
        "case.0.manual.1",
        accepted=True,
        note="listened",
    )

    accepted = service.accept_run(task.run_id, note="approved locally")

    assert accepted.acceptance is not None
    assert b"approved locally" in service.read_report(task.run_id, "json")
    with pytest.raises(ParityNotReadyError, match="already accepted"):
        service.accept_run(task.run_id, note="replace acceptance")
    with pytest.raises(ParityNotReadyError, match="accepted run"):
        service.record_manual_item(
            task.run_id,
            "case.0.manual.1",
            accepted=False,
            note="rewrite",
        )


def test_acceptance_recomputes_case_status_from_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.parity.service.validate_case",
        lambda case, assets, *, probe, measurements: CaseResult(
            case.case_id,
            "pass",
            (CheckResult("output_format", "blocked", "reference unavailable"),),
        ),
    )
    service = ParityService(
        _catalogue(),
        ParityRepository(tmp_path / "state"),
        TaskRegistry(),
    )
    task = _start(service, _manifest(tmp_path))
    _join(task)
    service.record_manual_item(
        task.run_id,
        "case.0.manual.1",
        accepted=True,
        note="listened",
    )

    with pytest.raises(ParityNotReadyError, match="blocked"):
        service.accept_run(task.run_id, note="reviewed")


def test_interrupted_task_reconciles_partial_run_and_rejects_acceptance(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry()
    task = registry.create("native-parity-validation")
    catalogue = _catalogue()
    repository = ParityRepository(tmp_path / "state")
    service = ParityService(
        catalogue,
        repository,
        registry,
    )
    manifest = _manifest(tmp_path)
    repository.create_run(
        ParityRun(
            run_id="interrupted-run",
            task_id=task.task_id,
            status="running",
            catalogue_version=catalogue.version,
            catalogue_hash=catalogue_digest(catalogue),
            manifest_path=str(manifest),
            manifest_hash=file_digest(manifest),
            app_version="15.0",
            created_at="2026-08-30T10:00:00+00:00",
            report_json_path="reports/interrupted-run.json",
            report_markdown_path="reports/interrupted-run.md",
            required_case_ids=("case.0",),
            manual_items=(
                ManualItem(
                    item_id="case.0.manual.1",
                    case_id="case.0",
                    prompt="Confirm case 0",
                ),
            ),
            thresholds={"case.0": {"duration_absolute_ms": 250}},
        )
    )
    registry.finish(task.task_id, status=INTERRUPTED)

    run = service.get_run("interrupted-run")

    assert run is not None
    assert run.status == "interrupted"
    with pytest.raises(ParityNotReadyError, match="interrupted"):
        service.accept_run(run.run_id, note="reviewed")
