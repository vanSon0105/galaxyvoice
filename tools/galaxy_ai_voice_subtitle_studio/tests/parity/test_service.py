from __future__ import annotations

import json
import threading
from hashlib import sha256
from pathlib import Path

import pytest

from app.common.cache import file_digest
from app.parity import CaseResult, CheckResult, ParityCase, ParityCatalogue
from app.parity.repository import ManualAnswer, ManualItem, ParityRepository, ParityRun
from app.parity.service import (
    ParityNotReadyError,
    ParityService,
    StartParityRun,
    ThresholdOverrideRequest,
    catalogue_digest,
)
from app.runtime.jobs import (
    CANCELLED,
    DONE,
    FAILED,
    INTERRUPTED,
    MAX_TASK_RECORDS,
    TaskRegistry,
)


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
    threshold_overrides: tuple[ThresholdOverrideRequest, ...] = (),
):
    return service.start_run(
        StartParityRun(
            manifest_path=manifest,
            approved_roots=(manifest.parent,),
            app_version="15.0",
            measurements_by_case=measurements or {},
            threshold_overrides=threshold_overrides,
        )
    )


def _join(task) -> None:
    assert task.thread is not None
    task.thread.join(timeout=5)
    assert not task.thread.is_alive()


def _passing_validator(case, assets, *, probe, measurements, **_kwargs):
    return CaseResult(
        case.case_id,
        "pass",
        tuple(CheckResult(check_id, "pass", "ok") for check_id in case.checks),
    )


def test_start_run_uses_task_registry_contract_and_serializes_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.parity.service.validate_case",
        _passing_validator,
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


def test_published_report_paths_identify_current_canonical_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.parity.service.validate_case", _passing_validator)
    repository = ParityRepository(tmp_path / "state")
    service = ParityService(_catalogue(), repository, TaskRegistry())
    task = _start(service, _manifest(tmp_path))
    _join(task)

    run = service.get_run(task.run_id)
    assert run is not None
    json_path = repository.root / run.report_json_path
    markdown_path = repository.root / run.report_markdown_path
    json_bytes = service.read_report(task.run_id, "json")

    assert json_path.read_bytes() == json_bytes
    assert markdown_path.read_bytes() == service.read_report(task.run_id, "markdown")
    report_paths = json.loads(json_bytes)["report_paths"]
    assert report_paths == {
        "json": run.report_json_path,
        "markdown": run.report_markdown_path,
    }
    assert "/revisions/" in run.report_json_path


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
        lambda _run, **_kwargs: (_ for _ in ()).throw(PermissionError("state is locked")),
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


def test_acceptance_recomputes_snapshot_hashes_and_manual_answers(
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
    service.repository.manifest_snapshot_path(task.run_id).write_bytes(b"tampered")
    with pytest.raises(ParityNotReadyError, match="manifest"):
        service.accept_run(task.run_id, note="reviewed")


def test_acceptance_rejects_changed_selected_manifest_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.parity.service.validate_case", _passing_validator)
    manifest = _manifest(tmp_path)
    service = ParityService(
        _catalogue(),
        ParityRepository(tmp_path / "state"),
        TaskRegistry(),
    )
    task = _start(service, manifest)
    _join(task)
    service.record_manual_item(
        task.run_id,
        "case.0.manual.1",
        accepted=True,
        note="listened",
    )
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_id": "changed-source",
                "created_at": "2026-08-30T00:00:00Z",
                "cases": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ParityNotReadyError, match="manifest source"):
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
        service.task_registry,
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
    task = registry.create("native-parity-validation", run_id="interrupted-run")
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
            manifest_snapshot_path="inputs/manifest.json",
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
        ),
        manifest_bytes=manifest.read_bytes(),
    )
    registry.finish(task.task_id, status=INTERRUPTED)

    run = service.get_run("interrupted-run")

    assert run is not None
    assert run.status == "interrupted"
    with pytest.raises(ParityNotReadyError, match="interrupted"):
        service.accept_run(run.run_id, note="reviewed")


def test_acceptance_reconstructs_required_case_check_and_manual_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalogue = ParityCatalogue(
        version="v1",
        cases=(
            ParityCase(
                case_id="case.0",
                area="studio",
                title="Case 0",
                required=True,
                checks=("output_format", "duration"),
                manual_prompts=("Confirm case 0",),
                thresholds={"duration_absolute_ms": 250},
            ),
        ),
    )
    monkeypatch.setattr(
        "app.parity.service.validate_case",
        lambda case, assets, *, probe, measurements, **_kwargs: CaseResult(
            case.case_id,
            "pass",
            (CheckResult("output_format", "pass", "only one check"),),
        ),
    )
    service = ParityService(
        catalogue,
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

    with pytest.raises(ParityNotReadyError, match="check contract"):
        service.accept_run(task.run_id, note="reviewed")


def test_acceptance_rejects_tampered_empty_and_extra_contract_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.parity.service.validate_case", _passing_validator)
    repository = ParityRepository(tmp_path / "state")
    service = ParityService(_catalogue(), repository, TaskRegistry())
    task = _start(service, _manifest(tmp_path))
    _join(task)
    run_path = repository.root / "runs" / task.run_id / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["required_case_ids"] = []
    payload["manual_items"] = []
    payload["case_results"].append(
        {
            "case_id": "extra.case",
            "status": "pass",
            "checks": [],
        }
    )
    run_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises((KeyError, ParityNotReadyError)):
        service.accept_run(task.run_id, note="reviewed")


def test_acceptance_requires_matching_task_to_be_terminal_done(
    tmp_path: Path,
) -> None:
    catalogue = _catalogue()
    registry = TaskRegistry()
    task = registry.create("native-parity-validation", run_id="run-running-task")
    repository = ParityRepository(tmp_path / "state")
    manifest = _manifest(tmp_path)
    manifest_bytes = manifest.read_bytes()
    run = ParityRun(
        run_id="run-running-task",
        task_id=task.task_id,
        status="running",
        catalogue_version=catalogue.version,
        catalogue_hash=catalogue_digest(catalogue),
        manifest_path=str(manifest),
        manifest_hash=sha256(manifest_bytes).hexdigest(),
        manifest_snapshot_path="inputs/manifest.json",
        app_version="15.0",
        created_at="2026-08-30T10:00:00+00:00",
        report_json_path="reports/run-running-task/current.json",
        report_markdown_path="reports/run-running-task/current.md",
        required_case_ids=("case.0",),
        manual_items=(ManualItem("case.0.manual.1", "case.0", "Confirm case 0"),),
        thresholds={"case.0": {"duration_absolute_ms": 250}},
    )
    repository.create_run(run, manifest_bytes=manifest_bytes)
    repository.record_case_result(
        run.run_id,
        CaseResult("case.0", "pass", (CheckResult("output_format", "pass", "ok"),)),
    )
    repository.finish_run(
        run.run_id,
        status="completed",
        case_results=repository.get_run(run.run_id).case_results,  # type: ignore[union-attr]
        warnings=(),
        completed_at="2026-08-30T10:05:00+00:00",
    )
    repository.record_manual_answer(
        run.run_id,
        ManualAnswer("case.0.manual.1", True, "listened", "2026-08-30T10:06:00+00:00"),
    )

    service = ParityService(catalogue, repository, registry)
    with pytest.raises(ParityNotReadyError, match="done"):
        service.accept_run(run.run_id, note="reviewed")


def test_worker_inspects_run_owned_manifest_snapshot_not_swapped_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _manifest(tmp_path)
    original_bytes = source.read_bytes()
    inspected_corpus_ids: list[str] = []
    real_inspect = __import__("app.parity.corpus", fromlist=["inspect_manifest"]).inspect_manifest

    def inspect_snapshot(manifest, *, approved_roots, asset_root):
        inspected_corpus_ids.append(manifest.corpus_id)
        source.write_text("replacement corpus", encoding="utf-8")
        source.write_bytes(original_bytes)
        return real_inspect(
            manifest,
            approved_roots=approved_roots,
            asset_root=asset_root,
        )

    monkeypatch.setattr("app.parity.service.inspect_manifest", inspect_snapshot)
    monkeypatch.setattr("app.parity.service.validate_case", _passing_validator)
    service = ParityService(
        _catalogue(),
        ParityRepository(tmp_path / "state"),
        TaskRegistry(),
    )

    task = _start(service, source)
    _join(task)

    assert task.status == DONE
    assert inspected_corpus_ids == ["test-corpus"]
    assert service.repository.manifest_snapshot_path(task.run_id).read_bytes() == original_bytes


def test_worker_uses_captured_manifest_when_snapshot_swaps_inside_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_asset = tmp_path / "original.bin"
    swapped_asset = tmp_path / "swapped.bin"
    original_asset.write_bytes(b"original")
    swapped_asset.write_bytes(b"swapped")

    def manifest_bytes(corpus_id: str, role: str, asset: Path) -> bytes:
        return json.dumps(
            {
                "schema_version": 1,
                "corpus_id": corpus_id,
                "created_at": "2026-08-30T00:00:00Z",
                "cases": [
                    {
                        "case_id": "case.0",
                        "assets": [
                            {
                                "role": role,
                                "path": asset.name,
                                "sha256": sha256(asset.read_bytes()).hexdigest(),
                                "byte_size": asset.stat().st_size,
                            }
                        ],
                    }
                ],
            }
        ).encode("utf-8")

    source = tmp_path / "manifest.json"
    original_bytes = manifest_bytes("original", "original-role", original_asset)
    swapped_bytes = manifest_bytes("swapped", "swapped-role", swapped_asset)
    source.write_bytes(original_bytes)
    catalogue = ParityCatalogue(
        version="v1",
        cases=(
            ParityCase(
                case_id="case.0",
                area="studio",
                title="Case 0",
                required=True,
                fixture_roles=("original-role",),
                checks=("output_format",),
                manual_prompts=(),
                thresholds={"duration_absolute_ms": 250},
            ),
        ),
    )
    repository = ParityRepository(tmp_path / "state")
    real_inspect = __import__("app.parity.corpus", fromlist=["inspect_manifest"]).inspect_manifest
    swapped_snapshots: list[Path] = []

    def swap_inside_inspect(manifest, *, approved_roots, asset_root):
        snapshot = next((repository.root / "runs").glob("*/inputs/manifest.json"))
        swapped_snapshots.append(snapshot)
        snapshot.write_bytes(swapped_bytes)
        try:
            return real_inspect(
                manifest,
                approved_roots=approved_roots,
                asset_root=asset_root,
            )
        finally:
            snapshot.write_bytes(original_bytes)

    seen_assets: list[set[str]] = []

    def validate(case, assets, *, probe, measurements, **_kwargs):
        seen_assets.append(set(assets))
        return _passing_validator(
            case,
            assets,
            probe=probe,
            measurements=measurements,
        )

    monkeypatch.setattr("app.parity.service.inspect_manifest", swap_inside_inspect)
    monkeypatch.setattr("app.parity.service.validate_case", validate)
    service = ParityService(
        catalogue,
        repository,
        TaskRegistry(),
    )

    task = _start(service, source)
    _join(task)

    assert task.status == DONE
    assert len(swapped_snapshots) == 1
    assert seen_assets == [{"original-role"}]


def test_acceptance_holds_matching_done_task_through_repository_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.parity.service.validate_case", _passing_validator)
    registry = TaskRegistry()
    repository = ParityRepository(tmp_path / "state")
    service = ParityService(_catalogue(), repository, registry)
    task = _start(service, _manifest(tmp_path))
    _join(task)
    service.record_manual_item(
        task.run_id,
        "case.0.manual.1",
        accepted=True,
        note="listened",
    )
    for index in range(MAX_TASK_RECORDS - 1):
        filler = registry.create(f"filler-{index}")
        registry.finish(filler.task_id, status=DONE)

    commit_entered = threading.Event()
    create_attempted = threading.Event()
    create_finished = threading.Event()
    task_present_at_commit: list[bool] = []
    real_commit = repository.commit_acceptance

    def observed_commit(snapshot, acceptance):
        commit_entered.set()
        assert create_attempted.wait(timeout=5)
        create_finished.wait(timeout=1)
        task_present_at_commit.append(registry.get(task.task_id) is not None)
        return real_commit(snapshot, acceptance)

    def create_pruning_task() -> None:
        assert commit_entered.wait(timeout=5)
        create_attempted.set()
        registry.create("pruning-task")
        create_finished.set()

    monkeypatch.setattr(repository, "commit_acceptance", observed_commit)
    creator = threading.Thread(target=create_pruning_task)
    creator.start()
    accepted = service.accept_run(task.run_id, note="approved")
    creator.join(timeout=5)

    assert not creator.is_alive()
    assert accepted.acceptance is not None
    assert task_present_at_commit == [True]


def test_acceptance_compare_and_commit_detects_manual_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.parity.service.validate_case", _passing_validator)
    repository = ParityRepository(tmp_path / "state")
    service = ParityService(_catalogue(), repository, TaskRegistry())
    task = _start(service, _manifest(tmp_path))
    _join(task)
    service.record_manual_item(
        task.run_id,
        "case.0.manual.1",
        accepted=True,
        note="positive",
    )
    real_commit = repository.commit_acceptance

    def race(snapshot, acceptance):
        repository.record_manual_answer(
            task.run_id,
            ManualAnswer(
                "case.0.manual.1",
                False,
                "raced negative",
                "2026-08-30T10:07:00+00:00",
            ),
        )
        return real_commit(snapshot, acceptance)

    monkeypatch.setattr(repository, "commit_acceptance", race)

    with pytest.raises(ParityNotReadyError, match="changed"):
        service.accept_run(task.run_id, note="approved")
    assert repository.get_run(task.run_id).acceptance is None  # type: ignore[union-attr]


def test_submit_failure_terminalizes_task_and_run_with_same_persisted_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = TaskRegistry()
    repository = ParityRepository(tmp_path / "state")
    service = ParityService(_catalogue(), repository, registry)

    def fail_submit(*_args, **_kwargs):
        raise RuntimeError("thread creation failed")

    monkeypatch.setattr(registry, "submit", fail_submit)
    with pytest.raises(RuntimeError, match="thread creation failed"):
        _start(service, _manifest(tmp_path))

    task_payload = registry.snapshot()[0]
    assert task_payload["status"] == FAILED
    run = repository.get_run(task_payload["run_id"])
    assert run is not None
    assert run.status == "failed"
    assert run.run_id == task_payload["run_id"]


def test_threshold_overrides_record_provenance_and_gate_relaxation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.parity.service.validate_case", _passing_validator)
    service = ParityService(
        _catalogue(),
        ParityRepository(tmp_path / "state"),
        TaskRegistry(),
    )
    override = ThresholdOverrideRequest(
        case_id="case.0",
        threshold_id="duration_absolute_ms",
        value=300,
        provenance="local reviewer",
        note="Reference has a deliberate trailing pause",
    )
    task = _start(service, _manifest(tmp_path), threshold_overrides=(override,))
    _join(task)
    run = service.get_run(task.run_id)

    assert run is not None
    assert run.threshold_overrides[0].relaxation is True
    assert run.threshold_overrides[0].provenance == "local reviewer"
    assert b'"relaxation":true' in service.read_report(task.run_id, "json")
    service.record_manual_item(
        task.run_id,
        "case.0.manual.1",
        accepted=True,
        note="listened",
    )
    accepted = service.accept_run(task.run_id, note="Explicitly accept relaxed threshold")
    assert accepted.acceptance is not None


def test_threshold_override_requires_provenance_and_note(tmp_path: Path) -> None:
    service = ParityService(
        _catalogue(),
        ParityRepository(tmp_path / "state"),
        TaskRegistry(),
    )
    override = ThresholdOverrideRequest(
        case_id="case.0",
        threshold_id="duration_absolute_ms",
        value=300,
        provenance="",
        note="",
    )

    with pytest.raises(ValueError, match="provenance|note"):
        _start(service, _manifest(tmp_path), threshold_overrides=(override,))


def test_tightening_threshold_remains_eligible_for_normal_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.parity.service.validate_case", _passing_validator)
    service = ParityService(
        _catalogue(),
        ParityRepository(tmp_path / "state"),
        TaskRegistry(),
    )
    override = ThresholdOverrideRequest(
        case_id="case.0",
        threshold_id="duration_absolute_ms",
        value=200,
        provenance="local reviewer",
        note="Use the stricter release tolerance",
    )
    task = _start(service, _manifest(tmp_path), threshold_overrides=(override,))
    _join(task)
    run = service.get_run(task.run_id)

    assert run is not None
    assert run.threshold_overrides[0].relaxation is False
    assert run.thresholds["case.0"]["duration_absolute_ms"] == 200
    service.record_manual_item(
        task.run_id,
        "case.0.manual.1",
        accepted=True,
        note="listened",
    )
    accepted = service.accept_run(task.run_id, note="Accept stricter evidence")
    assert accepted.acceptance is not None
