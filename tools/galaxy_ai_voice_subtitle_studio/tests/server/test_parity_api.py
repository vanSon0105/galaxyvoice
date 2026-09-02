from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.parity import (
    AcceptanceRecord,
    AssetInspection,
    CaseResult,
    CheckResult,
    CorpusInspection,
    Finding,
    ManifestAsset,
    ManifestCase,
    MediaExpectation,
    MediaInfo,
    MigrationAsset,
    MigrationCandidate,
    MigrationDryRun,
    MigrationFinding,
    ParityCase,
    ParityCatalogue,
    ParityFixtureManifest,
    ParityNotReadyError,
    ParityRepository,
    ParityService,
    SourceFingerprint,
    StartParityRun,
)
from app.parity.repository import ManualAnswer, ManualItem, ParityRun
from app.parity.evidence import (
    ArtifactCheckEvidence,
    CancellationCheckEvidence,
    DurationCheckEvidence,
    IdentityCheckEvidence,
    LoudnessCheckEvidence,
    MediaCheckEvidence,
    MigrationCheckEvidence,
    PerformanceCheckEvidence,
    RecoveryCheckEvidence,
    SubtitleCheckEvidence,
)
from app.parity.security import UnsafePathError
from app.parity.validators import PerformanceSample, RecoverySample
from app.runtime.jobs import TaskRecord, TaskRegistry
from app.server.main import create_app


def _fingerprint(seed: str) -> SourceFingerprint:
    return SourceFingerprint(
        kind="file",
        sha256=(seed * 64)[:64],
        byte_size=12,
        entry_count=1,
    )


def _manifest(tmp_path: Path, *, schema_version: int = 1) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "corpus_id": "api-corpus",
                "created_at": "2026-08-30T00:00:00Z",
                "cases": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _start_payload(manifest: Path) -> dict[str, object]:
    return {
        "manifest_path": str(manifest),
        "approved_roots": [str(manifest.parent)],
    }


def _catalogue() -> ParityCatalogue:
    return ParityCatalogue(
        version="2026-08-30",
        cases=(
            ParityCase(
                case_id="shared.project_portability",
                area="shared",
                title="Project portability and handoff",
                required=True,
                fixture_roles=("portable_project",),
                checks=("project_reopen",),
                manual_prompts=("Confirm portability.",),
                thresholds={"duration_absolute_ms": 250},
            ),
        ),
    )


def _corpus() -> CorpusInspection:
    manifest = ParityFixtureManifest(
        schema_version=1,
        corpus_id="api-corpus",
        created_at="2026-08-30T00:00:00Z",
        cases=(
            ManifestCase(
                case_id="shared.project_portability",
                assets=(
                    ManifestAsset(
                        role="portable_project",
                        path="portable.json",
                        sha256="a" * 64,
                        byte_size=12,
                        media=MediaExpectation(extension=".json"),
                    ),
                ),
            ),
        ),
    )
    return CorpusInspection(
        manifest=manifest,
        assets_by_role={
            "portable_project": AssetInspection(
                role="portable_project",
                path=Path("C:/fixtures/portable.json"),
                status="ready",
                findings=(Finding(code="ready", message="Fixture is ready"),),
                media=MediaInfo(container="json"),
            )
        },
        roles_by_case={"shared.project_portability": ("portable_project",)},
    )


def _migration() -> MigrationDryRun:
    before = _fingerprint("b")
    candidate = MigrationCandidate(
        source_id="voice-1",
        target="voice_profile",
        data={"name": "Narrator"},
        assets=(MigrationAsset(role="reference_audio", hint="voice.wav", state="linked"),),
        warnings=("Review consent",),
    )
    return MigrationDryRun(
        source_before=before,
        source_after=before,
        voice_profiles=(candidate,),
        assets=candidate.assets,
        unsupported=(MigrationFinding(source="settings", reason="unsupported"),),
        warnings=("Dry run only",),
    )


def _run(*, status: str = "completed") -> ParityRun:
    return ParityRun(
        run_id="run-1",
        task_id="native-parity-validation_task1",
        status=status,  # type: ignore[arg-type]
        catalogue_version="2026-08-30",
        catalogue_hash="c" * 64,
        manifest_path="C:/fixtures/manifest.json",
        manifest_hash="d" * 64,
        manifest_snapshot_path="inputs/manifest.json",
        app_version="0.1.0",
        created_at="2026-08-30T00:00:00Z",
        completed_at=("2026-08-30T00:01:00Z" if status != "running" else None),
        report_json_path="reports/run-1/report.json",
        report_markdown_path="reports/run-1/report.md",
        required_case_ids=("shared.project_portability",),
        manual_items=(
            ManualItem(
                item_id="shared.project_portability:manual:1",
                case_id="shared.project_portability",
                prompt="Confirm portability.",
            ),
        ),
        thresholds={"shared.project_portability": {"duration_absolute_ms": 250}},
        source_fingerprints={"manifest": _fingerprint("d")},
        case_results=(
            CaseResult(
                case_id="shared.project_portability",
                status="pass",
                checks=(
                    CheckResult(
                        check_id="project_reopen",
                        status="pass",
                        message="ok",
                        measurements={"duration_ms": 120},
                    ),
                ),
            ),
        ),
    )


class StubParityService:
    def __init__(self) -> None:
        self.run = _run()
        self.corpus_request: tuple[Path, tuple[Path, ...]] | None = None
        self.migration_request: tuple[Path, tuple[Path, ...], bool] | None = None
        self.start_request: StartParityRun | None = None

    def list_catalogue(self) -> ParityCatalogue:
        return _catalogue()

    def inspect_corpus(
        self, manifest_path: Path, *, approved_roots: tuple[Path, ...]
    ) -> CorpusInspection:
        if ".." in manifest_path.parts:
            raise UnsafePathError("Path is outside the approved roots")
        self.corpus_request = (manifest_path, approved_roots)
        return _corpus()

    def inspect_migration(
        self,
        source: Path,
        *,
        approved_roots: tuple[Path, ...],
        copied_source_confirmed: bool,
    ) -> MigrationDryRun:
        if ".." in source.parts:
            raise UnsafePathError("Path is outside the approved roots")
        self.migration_request = (source, approved_roots, copied_source_confirmed)
        if copied_source_confirmed is not True:
            raise ValueError("Explicit copied source confirmation is required")
        return _migration()

    def start_run(self, request: StartParityRun) -> TaskRecord:
        if ".." in request.manifest_path.parts:
            raise UnsafePathError("Path is outside the approved roots")
        self.start_request = request
        return TaskRecord(
            task_id="native-parity-validation_task1",
            kind="native-parity-validation",
            run_id="run-1",
        )

    def list_runs(self) -> tuple[ParityRun, ...]:
        return (self.run,)

    def get_run(self, run_id: str) -> ParityRun | None:
        return self.run if run_id == self.run.run_id else None

    def ready_for_acceptance(self, run_id: str) -> bool:
        return (
            run_id == self.run.run_id
            and self.run.status == "completed"
            and all(
                answer.accepted
                for item in self.run.manual_items
                if (answer := self.run.manual_answers.get(item.item_id)) is not None
            )
            and len(self.run.manual_answers) == len(self.run.manual_items)
            and self.run.acceptance is None
        )

    def get_run_detail(self, run_id: str):
        if run_id != self.run.run_id:
            return None
        return SimpleNamespace(
            run=self.run,
            ready_for_acceptance=self.ready_for_acceptance(run_id),
        )

    def read_report(self, run_id: str, report_format: str) -> bytes:
        if run_id != self.run.run_id:
            raise FileNotFoundError(run_id)
        if report_format == "json":
            return b'{"run_id":"run-1"}\n'
        if report_format == "markdown":
            return b"# Parity run run-1\n"
        raise ValueError(report_format)

    def record_manual_item(
        self,
        run_id: str,
        item_id: str,
        *,
        accepted: bool,
        note: str,
    ) -> ParityRun:
        if run_id != self.run.run_id:
            raise KeyError(run_id)
        answer = ManualAnswer(
            item_id=item_id,
            accepted=accepted,
            note=note,
            answered_at="2026-08-30T00:02:00Z",
        )
        self.run = replace(self.run, manual_answers={item_id: answer})
        return self.run

    def accept_run(self, run_id: str, *, note: str) -> ParityRun:
        if run_id == "incomplete":
            raise ParityNotReadyError("Parity run status running cannot be accepted")
        if run_id != self.run.run_id:
            raise KeyError(run_id)
        self.run = replace(
            self.run,
            acceptance=AcceptanceRecord(
                note=note,
                accepted_at="2026-08-30T00:03:00Z",
                catalogue_hash=self.run.catalogue_hash,
                manifest_hash=self.run.manifest_hash,
            ),
        )
        return self.run


class FalseyParityService(StubParityService):
    def __bool__(self) -> bool:
        return False


@pytest.fixture
def service() -> StubParityService:
    return StubParityService()


@pytest.fixture
def client(tmp_path: Path, service: StubParityService):
    app = create_app(
        config_path=tmp_path / "config.json",
        parity_service=service,
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def real_service(
    tmp_path: Path,
) -> tuple[ParityService, ParityRepository, TaskRegistry]:
    repository = ParityRepository(tmp_path / "parity-state")
    registry = TaskRegistry()
    return ParityService(_catalogue(), repository, registry), repository, registry


def test_catalogue_and_openapi_contract(client: TestClient) -> None:
    response = client.get("/api/parity/catalogue")

    assert response.status_code == 200
    assert response.json()["version"] == "2026-08-30"
    assert response.json()["cases"][0]["case_id"] == "shared.project_portability"

    parity_paths = {
        path: set(operations)
        for path, operations in client.get("/openapi.json").json()["paths"].items()
        if path.startswith("/api/parity")
    }
    assert parity_paths == {
        "/api/parity/catalogue": {"get"},
        "/api/parity/corpus/inspect": {"post"},
        "/api/parity/migration/inspect": {"post"},
        "/api/parity/runs": {"get", "post"},
        "/api/parity/runs/{run_id}": {"get"},
        "/api/parity/runs/{run_id}/report": {"get"},
        "/api/parity/runs/{run_id}/manual-items/{item_id}": {"post"},
        "/api/parity/runs/{run_id}/accept": {"post"},
    }


def test_run_detail_projects_backend_acceptance_readiness(
    client: TestClient,
    service: StubParityService,
) -> None:
    pending = client.get("/api/parity/runs/run-1")

    assert pending.status_code == 200
    assert pending.json()["ready_for_acceptance"] is False

    service.record_manual_item(
        "run-1",
        "shared.project_portability:manual:1",
        accepted=True,
        note="reviewed",
    )
    ready = client.get("/api/parity/runs/run-1")

    assert ready.status_code == 200
    assert ready.json()["ready_for_acceptance"] is True


def test_run_detail_does_not_combine_evidence_with_a_later_readiness_read(
    client: TestClient,
    service: StubParityService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.record_manual_item(
        "run-1",
        "shared.project_portability:manual:1",
        accepted=True,
        note="reviewed",
    )
    stale = replace(service.run, manual_answers={})
    monkeypatch.setattr(service, "get_run", lambda _run_id: stale)
    monkeypatch.setattr(service, "ready_for_acceptance", lambda _run_id: True)

    response = client.get("/api/parity/runs/run-1")

    assert response.status_code == 200
    assert response.json()["ready_for_acceptance"] is True
    assert response.json()["manual_answers"]["shared.project_portability:manual:1"][
        "accepted"
    ] is True


def test_corpus_and_migration_inspection_contract(
    client: TestClient, service: StubParityService
) -> None:
    corpus = client.post(
        "/api/parity/corpus/inspect",
        json={"manifest_path": "C:/fixtures/manifest.json", "approved_roots": ["C:/fixtures"]},
    )
    migration = client.post(
        "/api/parity/migration/inspect",
        json={
            "source": "C:/copies/omnivoice.db",
            "approved_roots": ["C:/copies"],
            "copied_source_confirmed": True,
        },
    )

    assert corpus.status_code == 200
    assert corpus.json()["manifest"]["corpus_id"] == "api-corpus"
    assert corpus.json()["assets_by_role"]["portable_project"]["status"] == "ready"
    assert service.corpus_request == (
        Path("C:/fixtures/manifest.json"),
        (Path("C:/fixtures"),),
    )
    assert migration.status_code == 200
    assert migration.json()["voice_profiles"][0]["target"] == "voice_profile"
    assert migration.json()["unsupported"][0]["source"] == "settings"
    assert service.migration_request == (
        Path("C:/copies/omnivoice.db"),
        (Path("C:/copies"),),
        True,
    )


def test_migration_requires_explicit_copied_source_confirmation(client: TestClient) -> None:
    payload = {"source": "C:/copies/omnivoice.db", "approved_roots": ["C:/copies"]}

    missing = client.post("/api/parity/migration/inspect", json=payload)
    rejected = client.post(
        "/api/parity/migration/inspect",
        json={**payload, "copied_source_confirmed": False},
    )

    assert missing.status_code == 422
    assert rejected.status_code == 422


def test_start_list_and_detail_response_shapes(
    client: TestClient,
    service: StubParityService,
) -> None:
    started = client.post(
        "/api/parity/runs",
        json={
            "manifest_path": "C:/fixtures/manifest.json",
            "approved_roots": ["C:/fixtures"],
            "evidence_by_case": {
                "shared.project_portability": {
                    "project_reopen": {
                        "kind": "artifact",
                        "role": "portable_project",
                        "sha256": "f" * 64,
                    }
                }
            },
            "threshold_overrides": [
                {
                    "case_id": "shared.project_portability",
                    "threshold_id": "duration_absolute_ms",
                    "value": 300,
                    "provenance": "local UAT",
                    "note": "temporary comparison tolerance",
                }
            ],
            "source_fingerprints": {
                "manifest": {
                    "kind": "file",
                    "sha256": "d" * 64,
                    "byte_size": 12,
                    "entry_count": 1,
                }
            },
            "reference_fingerprints": {
                "reference": {
                    "kind": "file",
                    "sha256": "e" * 64,
                    "byte_size": 24,
                    "entry_count": 1,
                }
            },
        },
    )
    listed = client.get("/api/parity/runs")
    detail = client.get("/api/parity/runs/run-1")

    assert started.status_code == 202
    assert started.json() == {
        "task_id": "native-parity-validation_task1",
        "run_id": "run-1",
    }
    assert service.start_request is not None
    assert service.start_request.manifest_path == Path("C:/fixtures/manifest.json")
    assert service.start_request.approved_roots == (Path("C:/fixtures"),)
    evidence = service.start_request.measurements_by_case[
        "shared.project_portability"
    ]["project_reopen"]
    assert evidence == ArtifactCheckEvidence(
        role="portable_project",
        sha256="f" * 64,
    )
    assert service.start_request.threshold_overrides[0].threshold_id == (
        "duration_absolute_ms"
    )
    assert service.start_request.source_fingerprints["manifest"] == _fingerprint("d")
    assert service.start_request.reference_fingerprints["reference"] == SourceFingerprint(
        kind="file",
        sha256="e" * 64,
        byte_size=24,
        entry_count=1,
    )
    assert listed.status_code == 200
    assert listed.json()["runs"][0] == {
        "run_id": "run-1",
        "task_id": "native-parity-validation_task1",
        "status": "completed",
        "catalogue_version": "2026-08-30",
        "app_version": "0.1.0",
        "created_at": "2026-08-30T00:00:00Z",
        "completed_at": "2026-08-30T00:01:00Z",
        "accepted": False,
    }
    assert detail.status_code == 200
    assert detail.json()["case_results"][0]["checks"][0]["measurements"] == {
        "duration_ms": 120
    }
    assert detail.json()["manual_items"][0]["item_id"].endswith(":manual:1")


def test_run_contract_parses_all_external_evidence_into_domain_types(
    client: TestClient,
    service: StubParityService,
) -> None:
    hardware = {
        "platform": "windows",
        "architecture": "amd64",
        "cpu_model": "Test CPU",
        "logical_cpu_count": 8,
        "memory_bytes": 17179869184,
        "accelerator_model": "Test GPU",
    }
    response = client.post(
        "/api/parity/runs",
        json={
            "manifest_path": "C:/fixtures/manifest.json",
            "approved_roots": ["C:/fixtures"],
            "evidence_by_case": {
                "case.all": {
                    "media": {
                        "kind": "media",
                        "role": "native_audio",
                        "expected": {"extension": ".wav", "audio_streams": 1},
                    },
                    "duration": {
                        "kind": "duration",
                        "native_seconds": 1.0,
                        "reference_seconds": 1.0,
                    },
                    "subtitles": {
                        "kind": "subtitles",
                        "native": [{"start_ms": 0, "end_ms": 500, "text": "Hello"}],
                        "reference": [{"start_ms": 0, "end_ms": 500, "text": "Hello"}],
                    },
                    "identity": {
                        "kind": "identity",
                        "native": {"speaker": "voice-1"},
                        "reference": {"speaker": "voice-1"},
                    },
                    "loudness": {"kind": "loudness", "measured_lufs": -16.0},
                    "performance": {
                        "kind": "performance",
                        "native": {
                            "wall_seconds": 1.1,
                            "peak_ram_bytes": 110,
                            "peak_vram_bytes": None,
                            "response_ms": [10, 20],
                            "applicable_metrics": ["wall_seconds", "peak_ram_bytes"],
                            "hardware_identity": hardware,
                            "resolved_device": "cpu",
                        },
                        "reference": {
                            "wall_seconds": 1.0,
                            "peak_ram_bytes": 100,
                            "peak_vram_bytes": None,
                            "response_ms": [8, 12],
                            "applicable_metrics": ["wall_seconds", "peak_ram_bytes"],
                            "hardware_identity": hardware,
                            "resolved_device": "cpu",
                        },
                    },
                    "recovery": {
                        "kind": "recovery",
                        "interrupted": True,
                        "task_status": "interrupted",
                        "resumable": True,
                        "recovery_route": "/settings/parity",
                    },
                    "cancellation": {
                        "kind": "cancellation",
                        "acknowledgement_seconds": 0.25,
                        "device": "cpu",
                    },
                    "artifact": {
                        "kind": "artifact",
                        "role": "portable_project",
                        "sha256": "a" * 64,
                    },
                    "migration": {
                        "kind": "migration",
                        "source_roles": ["voicestudio_copy", "persona_bundle"],
                        "copied_source_confirmed": True,
                    },
                }
            },
        },
    )

    assert response.status_code == 202
    assert service.start_request is not None
    evidence = service.start_request.measurements_by_case["case.all"]
    assert isinstance(evidence["media"], MediaCheckEvidence)
    assert isinstance(evidence["duration"], DurationCheckEvidence)
    assert isinstance(evidence["subtitles"], SubtitleCheckEvidence)
    assert isinstance(evidence["identity"], IdentityCheckEvidence)
    assert isinstance(evidence["loudness"], LoudnessCheckEvidence)
    assert isinstance(evidence["performance"], PerformanceCheckEvidence)
    assert isinstance(evidence["performance"].native, PerformanceSample)
    assert isinstance(evidence["recovery"], RecoveryCheckEvidence)
    assert isinstance(evidence["recovery"].sample, RecoverySample)
    assert isinstance(evidence["cancellation"], CancellationCheckEvidence)
    assert isinstance(evidence["artifact"], ArtifactCheckEvidence)
    assert isinstance(evidence["migration"], MigrationCheckEvidence)
    assert evidence["migration"].copied_source_confirmed is True


def test_raw_untyped_measurement_payload_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/parity/runs",
        json={
            "manifest_path": "C:/fixtures/manifest.json",
            "approved_roots": ["C:/fixtures"],
            "measurements_by_case": {
                "shared.project_portability": {"project_reopen": {"passed": True}}
            },
        },
    )

    assert response.status_code == 422


def test_run_migration_evidence_requires_explicit_copied_source_confirmation(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/parity/runs",
        json={
            "manifest_path": "C:/fixtures/manifest.json",
            "approved_roots": ["C:/fixtures"],
            "evidence_by_case": {
                "migration.voicestudio_copy": {
                    "source_immutability": {
                        "kind": "migration",
                        "source_roles": ["voicestudio_copy"],
                        "copied_source_confirmed": False,
                    }
                }
            },
        },
    )

    assert response.status_code == 422


def test_public_api_can_complete_and_accept_content_bound_evidence(
    tmp_path: Path,
) -> None:
    project = {"project_id": "project-1", "revision": 1, "content": {"text": "hello"}}
    project_digest = sha256(
        json.dumps(project, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    artifact = tmp_path / "portable.json"
    artifact.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "producer": "galaxy-ai-voice-subtitle-studio",
                "case_id": "shared.project_portability",
                "checks": {
                    "project_reopen": {
                        "kind": "repository_round_trip",
                        "before": project,
                        "after": project,
                        "before_sha256": project_digest,
                        "after_sha256": project_digest,
                        "before_location": "selected-root-a",
                        "after_location": "selected-root-a",
                    }
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    artifact_bytes = artifact.read_bytes()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_id": "public-contract",
                "created_at": "2026-08-30T00:00:00Z",
                "cases": [
                    {
                        "case_id": "shared.project_portability",
                        "assets": [
                            {
                                "role": "portable_project",
                                "path": artifact.name,
                                "sha256": sha256(artifact_bytes).hexdigest(),
                                "byte_size": len(artifact_bytes),
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    catalogue = ParityCatalogue(
        version="public-v1",
        cases=(
            ParityCase(
                case_id="shared.project_portability",
                area="shared",
                title="Project reopen",
                required=True,
                fixture_roles=("portable_project",),
                checks=("project_reopen",),
                manual_prompts=("Confirm project content.",),
            ),
        ),
    )
    registry = TaskRegistry()
    service = ParityService(
        catalogue,
        ParityRepository(tmp_path / "state"),
        registry,
    )
    app = create_app(parity_service=service)
    payload = {
        "manifest_path": str(manifest),
        "approved_roots": [str(tmp_path)],
        "evidence_by_case": {
            "shared.project_portability": {
                "project_reopen": {
                    "kind": "artifact",
                    "role": "portable_project",
                    "sha256": sha256(artifact_bytes).hexdigest(),
                }
            }
        },
    }

    with TestClient(app) as real_client:
        started = real_client.post("/api/parity/runs", json=payload)
        assert started.status_code == 202
        task = registry.get(started.json()["task_id"])
        assert task is not None and task.thread is not None
        task.thread.join(timeout=5)
        detail = real_client.get(f"/api/parity/runs/{started.json()['run_id']}")
        assert detail.status_code == 200
        assert detail.json()["case_results"][0]["status"] == "pass"
        assert detail.json()["ready_for_acceptance"] is False

        manual = real_client.post(
            f"/api/parity/runs/{started.json()['run_id']}/manual-items/"
            "shared.project_portability.manual.1",
            json={"accepted": True, "note": "Reviewed the reopened project."},
        )
        assert manual.status_code == 200
        assert manual.json()["ready_for_acceptance"] is True
        accepted = real_client.post(
            f"/api/parity/runs/{started.json()['run_id']}/accept",
            json={"note": "Accepted public evidence contract."},
        )
        assert accepted.status_code == 200
        report = real_client.get(
            f"/api/parity/runs/{started.json()['run_id']}/report?format=json"
        )
        assert report.status_code == 200
        assert report.json()["acceptance"]["note"] == "Accepted public evidence contract."

        missing = real_client.post(
            "/api/parity/runs",
            json={
                "manifest_path": str(manifest),
                "approved_roots": [str(tmp_path)],
                "evidence_by_case": {},
            },
        )
        missing_task = registry.get(missing.json()["task_id"])
        assert missing_task is not None and missing_task.thread is not None
        missing_task.thread.join(timeout=5)
        blocked = real_client.get(f"/api/parity/runs/{missing.json()['run_id']}")
        assert blocked.json()["case_results"][0]["status"] == "blocked"
        assert blocked.json()["ready_for_acceptance"] is False


def test_unknown_runs_and_reports_return_404(client: TestClient) -> None:
    assert client.get("/api/parity/runs/missing").status_code == 404
    assert client.get("/api/parity/runs/missing/report?format=json").status_code == 404
    assert (
        client.post(
            "/api/parity/runs/missing/manual-items/item-1",
            json={"accepted": True, "note": "reviewed"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/parity/runs/missing/accept",
            json={"note": "reviewed"},
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("route", "payload"),
    [
        (
            "/api/parity/runs/not-found/manual-items/item-1",
            {"accepted": True, "note": "reviewed"},
        ),
        (
            "/api/parity/runs/not-found/accept",
            {"note": "reviewed"},
        ),
        (
            "/api/parity/runs/bad!id/manual-items/item-1",
            {"accepted": True, "note": "reviewed"},
        ),
        (
            "/api/parity/runs/bad!id/accept",
            {"note": "reviewed"},
        ),
    ],
)
def test_real_service_unknown_run_mutations_return_sanitized_404(
    real_service: tuple[ParityService, ParityRepository, TaskRegistry],
    route: str,
    payload: dict[str, object],
) -> None:
    service, _, _ = real_service
    app = create_app(parity_service=service)

    with TestClient(app, raise_server_exceptions=False) as real_client:
        response = real_client.post(route, json=payload)

    assert response.status_code == 404
    assert response.json() == {"detail": "Không tìm thấy lần chạy parity."}


def test_report_content_types_are_pinned(client: TestClient) -> None:
    json_report = client.get("/api/parity/runs/run-1/report?format=json")
    markdown_report = client.get("/api/parity/runs/run-1/report?format=markdown")

    assert json_report.status_code == 200
    assert json_report.headers["content-type"] == "application/json"
    assert json_report.content == b'{"run_id":"run-1"}\n'
    assert markdown_report.status_code == 200
    assert markdown_report.headers["content-type"] == "text/markdown; charset=utf-8"
    assert markdown_report.content == b"# Parity run run-1\n"


def test_manual_answer_is_strict_and_returns_updated_run(client: TestClient) -> None:
    route = "/api/parity/runs/run-1/manual-items/shared.project_portability:manual:1"

    invalid = client.post(route, json={"accepted": "yes", "note": "reviewed"})
    empty_note = client.post(route, json={"accepted": True, "note": "   "})
    updated = client.post(route, json={"accepted": False, "note": "Needs another pass"})

    assert invalid.status_code == 422
    assert empty_note.status_code == 422
    assert updated.status_code == 200
    assert updated.json()["manual_answers"]["shared.project_portability:manual:1"] == {
        "item_id": "shared.project_portability:manual:1",
        "accepted": False,
        "note": "Needs another pass",
        "answered_at": "2026-08-30T00:02:00Z",
    }


def test_accept_maps_premature_run_to_409(client: TestClient) -> None:
    response = client.post(
        "/api/parity/runs/incomplete/accept",
        json={"note": "reviewed"},
    )

    assert response.status_code == 409
    assert "cannot be accepted" in response.json()["detail"]


def test_accept_returns_the_accepted_run(client: TestClient) -> None:
    response = client.post(
        "/api/parity/runs/run-1/accept",
        json={"note": "reviewed locally"},
    )

    assert response.status_code == 200
    assert response.json()["acceptance"]["note"] == "reviewed locally"


@pytest.mark.parametrize(
    ("collection", "fingerprint_id", "fingerprint"),
    [
        (
            "source_fingerprints",
            "source",
            {"kind": "wat", "sha256": "a" * 64, "byte_size": 1, "entry_count": 1},
        ),
        (
            "source_fingerprints",
            "source",
            {"kind": "file", "sha256": "x", "byte_size": 1, "entry_count": 1},
        ),
        (
            "source_fingerprints",
            "source",
            {"kind": "file", "sha256": "A" * 64, "byte_size": 1, "entry_count": 1},
        ),
        (
            "source_fingerprints",
            "source",
            {"kind": "file", "sha256": "a" * 64, "byte_size": -1, "entry_count": 1},
        ),
        (
            "source_fingerprints",
            "source",
            {"kind": "file", "sha256": "a" * 64, "byte_size": True, "entry_count": 1},
        ),
        (
            "source_fingerprints",
            "source",
            {"kind": "file", "sha256": "a" * 64, "byte_size": 1, "entry_count": 0},
        ),
        (
            "reference_fingerprints",
            "",
            {"kind": "directory", "sha256": "b" * 64, "byte_size": 0, "entry_count": 0},
        ),
        (
            "reference_fingerprints",
            "reference",
            {"kind": "directory", "sha256": "b" * 64, "byte_size": 0, "entry_count": "0"},
        ),
    ],
)
def test_malformed_fingerprint_creates_no_run_or_task(
    tmp_path: Path,
    real_service: tuple[ParityService, ParityRepository, TaskRegistry],
    collection: str,
    fingerprint_id: str,
    fingerprint: dict[str, object],
) -> None:
    service, repository, registry = real_service
    payload = _start_payload(_manifest(tmp_path))
    payload[collection] = {fingerprint_id: fingerprint}
    app = create_app(parity_service=service)

    with TestClient(app) as real_client:
        response = real_client.post("/api/parity/runs", json=payload)

    assert response.status_code == 422
    assert repository.list_runs() == ()
    assert registry.snapshot() == []


@pytest.mark.parametrize("case", ["missing", "schema"])
def test_invalid_manifest_creates_no_run_or_task_and_hides_selected_path(
    tmp_path: Path,
    real_service: tuple[ParityService, ParityRepository, TaskRegistry],
    case: str,
) -> None:
    service, repository, registry = real_service
    manifest = (
        tmp_path / "private" / "missing.json"
        if case == "missing"
        else _manifest(tmp_path, schema_version=999)
    )
    app = create_app(parity_service=service)

    with TestClient(app) as real_client:
        response = real_client.post(
            "/api/parity/runs",
            json=_start_payload(manifest),
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Dữ liệu parity đầu vào không hợp lệ."}
    assert str(tmp_path) not in response.text
    assert repository.list_runs() == ()
    assert registry.snapshot() == []


def test_unapproved_manifest_path_creates_no_run_or_task(
    tmp_path: Path,
    real_service: tuple[ParityService, ParityRepository, TaskRegistry],
) -> None:
    service, repository, registry = real_service
    manifest = _manifest(tmp_path)
    approved_root = tmp_path / "approved"
    approved_root.mkdir()
    app = create_app(parity_service=service)

    with TestClient(app) as real_client:
        response = real_client.post(
            "/api/parity/runs",
            json={
                "manifest_path": str(manifest),
                "approved_roots": [str(approved_root)],
            },
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "Đường dẫn parity không được phép."}
    assert str(tmp_path) not in response.text
    assert repository.list_runs() == ()
    assert registry.snapshot() == []


@pytest.mark.parametrize(
    ("route", "payload", "method_name"),
    [
        (
            "/api/parity/corpus/inspect",
            {"manifest_path": "C:/fixtures/manifest.json", "approved_roots": ["C:/fixtures"]},
            "inspect_corpus",
        ),
        (
            "/api/parity/migration/inspect",
            {
                "source": "C:/copies/omnivoice.db",
                "approved_roots": ["C:/copies"],
                "copied_source_confirmed": True,
            },
            "inspect_migration",
        ),
        (
            "/api/parity/runs",
            {"manifest_path": "C:/fixtures/manifest.json", "approved_roots": ["C:/fixtures"]},
            "start_run",
        ),
        (
            "/api/parity/runs/run-1/report?format=json",
            None,
            "read_report",
        ),
    ],
)
def test_path_io_failures_return_sanitized_500(
    service: StubParityService,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    payload: dict[str, object] | None,
    method_name: str,
) -> None:
    private_path = r"C:\Users\private-user\private\manifest.json"

    def fail(*_args: object, **_kwargs: object) -> object:
        raise PermissionError(13, "access denied", private_path)

    monkeypatch.setattr(service, method_name, fail)
    app = create_app(parity_service=service)

    with TestClient(app, raise_server_exceptions=False) as real_client:
        response = real_client.post(route, json=payload) if payload else real_client.get(route)

    assert response.status_code == 500
    assert response.json() == {"detail": "Không thể truy cập dữ liệu parity."}
    assert private_path not in response.text


def test_falsey_injected_service_is_preserved() -> None:
    service = FalseyParityService()

    app = create_app(parity_service=service)

    assert app.state.parity_service is service


@pytest.mark.parametrize(
    ("route", "payload"),
    [
        (
            "/api/parity/corpus/inspect",
            {
                "manifest_path": "C:/fixtures/../outside.json",
                "approved_roots": ["C:/fixtures"],
            },
        ),
        (
            "/api/parity/migration/inspect",
            {
                "source": "C:/copies/../live/omnivoice.db",
                "approved_roots": ["C:/copies"],
                "copied_source_confirmed": True,
            },
        ),
        (
            "/api/parity/runs",
            {
                "manifest_path": "C:/fixtures/../outside.json",
                "approved_roots": ["C:/fixtures"],
            },
        ),
    ],
)
def test_path_traversal_maps_to_422(
    client: TestClient,
    route: str,
    payload: dict[str, object],
) -> None:
    response = client.post(route, json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": "Đường dẫn parity không được phép."}
