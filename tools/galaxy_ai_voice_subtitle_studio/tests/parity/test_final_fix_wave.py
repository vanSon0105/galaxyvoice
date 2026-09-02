from __future__ import annotations

import json
import threading
import time
import zipfile
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from app.common.cache import stable_digest
from app.common.errors import TaskCancelledError
from app.parity.archive_policy import ArchivePolicy, validate_archive_members
from app.parity.behavior import run_repository_check
from app.parity.evidence import (
    ArtifactCheckEvidence,
    CancellationCheckEvidence,
    DurationCheckEvidence,
    HardwareIdentity,
    IdentityCheckEvidence,
    LoudnessCheckEvidence,
    MediaCheckEvidence,
    MigrationCheckEvidence,
    PerformanceCheckEvidence,
    RecoveryCheckEvidence,
    RepositoryCheckEvidence,
    SubtitleCheckEvidence,
)
from app.parity.models import ParityCase
from app.parity.migration import MigrationAsset, MigrationCandidate, MigrationDryRun
from app.parity.reports import render_reports
from app.parity.repository import ManualAnswer, ParityRepository
from app.parity.security import fingerprint_source, redact_report_value
from app.parity.service import ParityService
from app.parity.validators import PerformanceSample, validate_case
from app.runtime.jobs import CANCELLED, DONE, TaskRegistry
from app.project_graph.models import AssetReference, NodeRequest
from app.project_graph.service import ProjectGraphService
from app.voice_library.models import ConsentRecord

from .test_service import _catalogue, _join, _manifest, _passing_validator, _start


def _artifact_bytes(case_id: str, check_id: str, proof: dict[str, object]) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "producer": "galaxy-ai-voice-subtitle-studio",
                "case_id": case_id,
                "checks": {check_id: proof},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _round_trip_proof(*, moved: bool = False) -> dict[str, object]:
    project = {"project_id": "project-1", "revision": 4, "content": {"text": "hello"}}
    digest = stable_digest(project)
    return {
        "kind": "repository_round_trip",
        "before": project,
        "after": project,
        "before_sha256": digest,
        "after_sha256": digest,
        "before_location": "selected-root-a",
        "after_location": "selected-root-b" if moved else "selected-root-a",
    }


def _handoff_proof() -> dict[str, object]:
    source = {"project_id": "project-1", "revision": 4, "artifacts": ["source-1"]}
    returned = {
        "project_id": "project-1",
        "revision": 5,
        "artifacts": ["source-1", "returned-1"],
    }
    return {
        "kind": "handoff_return",
        "handoff_id": "handoff-1",
        "source": source,
        "returned": returned,
        "source_sha256": stable_digest(source),
        "returned_sha256": stable_digest(returned),
        "status": "returned",
    }


def _project_graph_fixture(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "relink-target.wav"
    target.write_bytes(b"relinked-content")
    graph = tmp_path / "project_graph.json"
    service = ProjectGraphService(graph)
    service.upsert_node(
        NodeRequest(
            project_id="project-1",
            workspace="studio",
            owner_id="take-1",
            label="Portable project",
            revision=4,
            assets=(
                AssetReference(
                    asset_id="asset-1",
                    role="reference_audio",
                    path_hint="missing/reference.wav",
                    fingerprint=sha256(target.read_bytes()).hexdigest(),
                    metadata={"relink_role": "relinked_asset"},
                ),
            ),
        )
    )
    return graph, target


@pytest.mark.parametrize(
    "check_id",
    [
        "project_reopen",
        "moved_directory_portability",
        "missing_media_relink",
        "handoff_return",
    ],
)
def test_behavioral_checks_run_through_project_graph_repositories(
    tmp_path: Path,
    check_id: str,
) -> None:
    graph, target = _project_graph_fixture(tmp_path)
    evidence = run_repository_check(
        "shared.project_portability",
        check_id,
        ArtifactCheckEvidence(
            role="portable_project",
            sha256=sha256(graph.read_bytes()).hexdigest(),
        ),
        {"portable_project": graph, "relinked_asset": target},
        approved_roots=(tmp_path,),
        check_cancelled=lambda: None,
    )

    result = validate_case(
        ParityCase(
            case_id="shared.project_portability",
            area="shared",
            title="Behavior",
            required=True,
            checks=(check_id,),
        ),
        {},
        probe=object(),  # type: ignore[arg-type]
        measurements={check_id: evidence},
    )

    assert isinstance(evidence, RepositoryCheckEvidence)
    assert result.status == "pass"
    assert result.checks[0].measurements["repository"] == "project_graph"


def test_checkpoint_resume_runs_through_longform_repository(tmp_path: Path) -> None:
    source = tmp_path / "story.txt"
    source.write_text("First paragraph. Second paragraph.", encoding="utf-8")

    evidence = run_repository_check(
        "longform.story",
        "checkpoint_resume",
        ArtifactCheckEvidence(
            role="story_script",
            sha256=sha256(source.read_bytes()).hexdigest(),
        ),
        {"story_script": source},
        approved_roots=(tmp_path,),
        check_cancelled=lambda: None,
    )

    assert evidence.status == "pass"
    assert evidence.measurements["repository"] == "longform_project"


def test_handwritten_behavior_proof_cannot_be_promoted_by_repository_runner(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "claimed-proof.json"
    artifact.write_bytes(
        _artifact_bytes("shared.project_portability", "project_reopen", _round_trip_proof())
    )

    evidence = run_repository_check(
        "shared.project_portability",
        "project_reopen",
        ArtifactCheckEvidence(
            role="portable_project",
            sha256=sha256(artifact.read_bytes()).hexdigest(),
        ),
        {"portable_project": artifact},
        approved_roots=(tmp_path,),
        check_cancelled=lambda: None,
    )

    assert evidence.status == "fail"
    assert "no nodes" in evidence.message


def test_forged_behavior_boolean_and_pass_field_never_pass(tmp_path: Path) -> None:
    artifact = tmp_path / "forged.json"
    artifact.write_bytes(
        _artifact_bytes("case.behavior", "project_reopen", {"passed": True})
    )
    case = ParityCase(
        case_id="case.behavior",
        area="shared",
        title="Behavior",
        required=True,
        fixture_roles=("artifact",),
        checks=("project_reopen",),
    )

    boolean = validate_case(
        case,
        {"artifact": artifact},
        probe=object(),  # type: ignore[arg-type]
        measurements={"project_reopen": True},
    )
    forged = validate_case(
        case,
        {"artifact": artifact},
        probe=object(),  # type: ignore[arg-type]
        measurements={
            "project_reopen": ArtifactCheckEvidence(
                role="artifact",
                sha256=sha256(artifact.read_bytes()).hexdigest(),
            )
        },
    )

    assert boolean.status != "pass"
    assert forged.status != "pass"


def test_migration_checks_pass_only_from_galaxy_dry_run_evidence() -> None:
    fingerprint = fingerprint_source(Path(__file__))
    dry_run = MigrationDryRun(
        source_before=fingerprint,
        source_after=fingerprint,
        voice_profiles=(
            MigrationCandidate(
                source_id="voice-1",
                target="voice_profile",
                consent=ConsentRecord(
                    confirmed=False,
                    statement="Re-attestation required",
                    provenance="voicestudio-copy",
                ),
            ),
        ),
        assets=(
            MigrationAsset(
                role="reference_audio",
                hint="<external-path:1>",
                state="missing",
                expected_sha256="a" * 64,
            ),
        ),
        sandbox_cleaned=True,
    )
    evidence = MigrationCheckEvidence(
        copied_source_confirmed=True,
        dry_runs=(dry_run,),
    )
    checks = (
        "source_immutability",
        "consent_mapping",
        "missing_media",
        "sandbox_cleanup",
    )
    case = ParityCase(
        case_id="migration.voicestudio_copy",
        area="migration",
        title="Migration",
        required=True,
        checks=checks,
    )

    result = validate_case(
        case,
        {},
        probe=object(),  # type: ignore[arg-type]
        measurements={check_id: evidence for check_id in checks},
    )

    assert result.status == "pass"
    assert tuple(check.status for check in result.checks) == ("pass",) * 4


def _hardware() -> HardwareIdentity:
    return HardwareIdentity(
        platform="windows",
        architecture="amd64",
        cpu_model="Test CPU",
        logical_cpu_count=8,
        memory_bytes=16 * 1024**3,
        accelerator_model="Test GPU",
    )


def test_performance_provenance_is_matched_and_reconstructable() -> None:
    from app.parity.validators import judge_performance

    native = PerformanceSample(
        app_version="15.0",
        wall_seconds=12.0,
        peak_ram_bytes=1_200,
        peak_vram_bytes=600,
        response_ms=(10.0, 30.0, 20.0),
        hardware_identity=_hardware(),
        resolved_device="cuda:0",
    )
    reference = PerformanceSample(
        app_version="VoiceStudio 0.4.2",
        wall_seconds=10.0,
        peak_ram_bytes=1_000,
        peak_vram_bytes=500,
        response_ms=(8.0, 12.0),
        hardware_identity=_hardware(),
        resolved_device="cuda:0",
    )

    result = judge_performance(native=native, reference=reference)

    assert result.status == "pass"
    assert result.measurements["native"]["wall_seconds"] == 12.0  # type: ignore[index]
    assert result.measurements["reference"]["peak_vram_bytes"] == 500  # type: ignore[index]
    assert result.measurements["hardware_identity"]["cpu_model"] == "Test CPU"  # type: ignore[index]
    assert result.measurements["response_p95_ms"] == 30.0


def test_performance_without_matching_hardware_provenance_is_blocked() -> None:
    from app.parity.validators import judge_performance

    native = PerformanceSample(
        app_version="15.0",
        wall_seconds=1.0,
        peak_ram_bytes=100,
        response_ms=(10.0,),
        applicable_metrics=frozenset({"wall_seconds", "peak_ram_bytes"}),
        hardware_identity=_hardware(),
        resolved_device="cpu",
    )
    reference = replace(
        native,
        hardware_identity=replace(_hardware(), cpu_model="Different CPU"),
    )

    assert judge_performance(native=native, reference=reference).status == "blocked"


def test_performance_without_app_version_provenance_is_blocked() -> None:
    from app.parity.validators import judge_performance

    native = PerformanceSample(
        wall_seconds=1.0,
        peak_ram_bytes=100,
        response_ms=(10.0,),
        applicable_metrics=frozenset({"wall_seconds", "peak_ram_bytes"}),
        hardware_identity=_hardware(),
        resolved_device="cpu",
    )
    reference = replace(native, app_version="VoiceStudio 0.4.2")

    assert judge_performance(native=native, reference=reference).status == "blocked"


def test_default_zip_probe_propagates_chunk_cancellation(tmp_path: Path) -> None:
    from app.parity.validators import DefaultMediaProbe

    archive_path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("payload.bin", b"x" * (128 * 1024))
    calls = 0

    def cancel_during_stream() -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise TaskCancelledError("cancelled")

    with pytest.raises(TaskCancelledError):
        DefaultMediaProbe(check_cancelled=cancel_during_stream).inspect(archive_path)

    assert calls >= 2


@pytest.mark.parametrize(
    "names",
    [
        ("CON.txt",),
        ("safe.txt:stream",),
        ("folder./item.txt",),
        ("caf\u00e9.txt", "cafe\u0301.txt"),
    ],
)
def test_shared_archive_policy_rejects_windows_aliases(names: tuple[str, ...]) -> None:
    infos = []
    for name in names:
        info = zipfile.ZipInfo(name)
        info.file_size = 1
        info.compress_size = 1
        infos.append(info)

    with pytest.raises(ValueError):
        validate_archive_members(infos, policy=ArchivePolicy())


def test_shared_archive_policy_rejects_encryption_and_unsupported_types() -> None:
    encrypted = zipfile.ZipInfo("safe.txt")
    encrypted.flag_bits |= 0x1
    unsupported = zipfile.ZipInfo("pipe")
    unsupported.external_attr = 0o010000 << 16

    with pytest.raises(ValueError, match="encrypted"):
        validate_archive_members([encrypted], policy=ArchivePolicy())
    with pytest.raises(ValueError, match="unsupported"):
        validate_archive_members([unsupported], policy=ArchivePolicy())


def test_shared_archive_policy_rejects_degenerate_dot_member() -> None:
    with pytest.raises(ValueError, match="member path"):
        validate_archive_members([zipfile.ZipInfo(".")], policy=ArchivePolicy())


@pytest.mark.parametrize(
    "names",
    [
        ("AUX.json",),
        ("safe.txt:ads",),
        ("folder /item.json",),
        ("r\u00e9sum\u00e9.json", "re\u0301sume\u0301.json"),
    ],
)
def test_migration_archive_preflight_uses_the_shared_windows_policy(
    names: tuple[str, ...],
) -> None:
    from app.parity import migration

    infos = [zipfile.ZipInfo(name) for name in names]
    assert migration._archive_rejection(infos)


def test_fingerprint_source_checks_cancellation_between_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.parity.security as security

    source = tmp_path / "large.bin"
    source.write_bytes(b"x" * 32)
    monkeypatch.setattr(security, "_HASH_CHUNK_SIZE", 4)
    checks = 0

    def check_cancelled() -> None:
        nonlocal checks
        checks += 1
        if checks >= 3:
            raise TaskCancelledError()

    with pytest.raises(TaskCancelledError):
        fingerprint_source(source, check_cancelled=check_cancelled)

    assert checks == 3


def test_ffprobe_is_terminated_when_cancellation_is_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.parity.validators as validators

    class Process:
        returncode = None
        terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return ("", "cancelled")

        def wait(self, timeout=None):
            return self.returncode

    process = Process()
    monkeypatch.setattr(validators, "find_ffprobe", lambda: "ffprobe")
    monkeypatch.setattr(validators.subprocess, "Popen", lambda *args, **kwargs: process)
    checks = 0

    def check_cancelled() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise TaskCancelledError()

    probe = validators.FfprobeMediaProbe(check_cancelled=check_cancelled, timeout_seconds=1)

    with pytest.raises(TaskCancelledError):
        probe.inspect(tmp_path / "video.mp4")

    assert process.terminated is True


def test_corpus_probe_cancellation_is_not_downgraded_to_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.parity.corpus import inspect_corpus
    from app.parity.validators import DefaultMediaProbe

    media = tmp_path / "sample.mp4"
    media.write_bytes(b"media")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_id": "cancel-probe",
                "created_at": "2026-08-30T00:00:00Z",
                "cases": [
                    {
                        "case_id": "case.cancel",
                        "assets": [
                            {
                                "role": "media",
                                "path": media.name,
                                "sha256": sha256(media.read_bytes()).hexdigest(),
                                "byte_size": media.stat().st_size,
                                "media": {"container": "mp4"},
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        DefaultMediaProbe,
        "inspect",
        lambda self, path: (_ for _ in ()).throw(TaskCancelledError()),
    )

    with pytest.raises(TaskCancelledError):
        inspect_corpus(
            manifest,
            approved_roots=(tmp_path,),
            check_cancelled=lambda: None,
        )


def test_completed_run_and_cancelled_task_cannot_split_terminal_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.parity.service.validate_case", _passing_validator)
    repository = ParityRepository(tmp_path / "state")
    registry = TaskRegistry()
    service = ParityService(_catalogue(), repository, registry)
    entered = threading.Event()
    release = threading.Event()
    real_finish = repository.finish_run

    def blocked_finish(*args, **kwargs):
        if kwargs.get("status") == "completed":
            entered.set()
            assert release.wait(timeout=5)
        return real_finish(*args, **kwargs)

    monkeypatch.setattr(repository, "finish_run", blocked_finish)
    task = _start(service, _manifest(tmp_path))
    assert entered.wait(timeout=5)
    cancellation: list[bool] = []
    thread = threading.Thread(
        target=lambda: cancellation.append(registry.cancel(task.task_id)),
        daemon=True,
    )
    thread.start()
    time.sleep(0.05)
    release.set()
    _join(task)
    thread.join(timeout=5)
    run = service.get_run(task.run_id)

    assert run is not None
    assert (run.status, task.status) in {("completed", DONE), ("cancelled", CANCELLED)}


def test_acceptance_publication_failure_is_retryable_without_stranded_acceptance(
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
        note="Reviewed",
    )
    real_stage_report = repository._stage_report_revision_unlocked
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise PermissionError("simulated accepted report publication failure")
        return real_stage_report(*args, **kwargs)

    monkeypatch.setattr(repository, "_stage_report_revision_unlocked", fail_once)

    with pytest.raises(PermissionError, match="publication failure"):
        service.accept_run(task.run_id, note="Approved")

    interrupted = repository.get_run(task.run_id)
    assert interrupted is not None
    assert interrupted.acceptance is None

    accepted = service.accept_run(task.run_id, note="Approved")
    report = json.loads(service.read_report(task.run_id, "json"))
    assert accepted.acceptance is not None
    assert report["acceptance"]["note"] == "Approved"


def test_acceptance_overlay_failure_after_report_staging_is_retry_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.parity.repository as repository_module

    monkeypatch.setattr("app.parity.service.validate_case", _passing_validator)
    repository = ParityRepository(tmp_path / "state")
    service = ParityService(_catalogue(), repository, TaskRegistry())
    task = _start(service, _manifest(tmp_path))
    _join(task)
    service.record_manual_item(
        task.run_id,
        "case.0.manual.1",
        accepted=True,
        note="Reviewed",
    )
    real_write = repository_module._write_json_atomic
    failed = False

    def fail_acceptance_once(path: Path, payload: object) -> None:
        nonlocal failed
        if path.name == "acceptance.json" and not failed:
            failed = True
            raise PermissionError("simulated acceptance overlay failure")
        real_write(path, payload)

    monkeypatch.setattr(repository_module, "_write_json_atomic", fail_acceptance_once)
    revisions = repository.root / "reports" / task.run_id / "revisions"
    before = {path.name for path in revisions.iterdir()}

    with pytest.raises(PermissionError, match="overlay failure"):
        service.accept_run(task.run_id, note="Approved")

    staged = {path.name for path in revisions.iterdir()}
    staged_acceptance = staged - before
    assert len(staged_acceptance) == 1
    assert repository.get_run(task.run_id).acceptance is None  # type: ignore[union-attr]

    accepted = service.accept_run(task.run_id, note="Approved")
    assert accepted.acceptance is not None
    assert accepted.acceptance.report_revision == staged_acceptance.pop()
    assert {path.name for path in revisions.iterdir()} == staged


def test_external_absolute_paths_are_replaced_without_basenames(tmp_path: Path) -> None:
    external = Path("Q:/selected-corpus")
    payload = {
        "warning": "ffprobe failed for Q:\\selected-corpus\\private\\voice-secret.wav",
        "other": "cannot open R:\\unapproved\\identity.json",
    }

    redacted = redact_report_value(payload, approved_roots=(external,))
    rendered = json.dumps(redacted)

    assert "Q:" not in rendered and "R:" not in rendered
    assert "voice-secret.wav" not in rendered and "identity.json" not in rendered
    assert "<external-path:1>" in rendered
    assert "<absolute-path>" in rendered


def test_redaction_preserves_relative_hints_and_galaxy_recovery_routes() -> None:
    payload = {
        "relative": "../missing/audio.wav",
        "recovery_route": "/settings/parity",
    }

    assert redact_report_value(payload) == payload


def test_public_evidence_domain_types_are_distinct_from_untyped_mappings() -> None:
    evidence_types = (
        MediaCheckEvidence,
        DurationCheckEvidence,
        SubtitleCheckEvidence,
        IdentityCheckEvidence,
        LoudnessCheckEvidence,
        PerformanceCheckEvidence,
        CancellationCheckEvidence,
        RecoveryCheckEvidence,
        ArtifactCheckEvidence,
        MigrationCheckEvidence,
    )

    assert len(set(evidence_types)) == 10
