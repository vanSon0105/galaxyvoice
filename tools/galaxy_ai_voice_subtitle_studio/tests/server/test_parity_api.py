from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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
    SourceFingerprint,
    StartParityRun,
)
from app.parity.repository import ManualAnswer, ManualItem, ParityRun
from app.parity.security import UnsafePathError
from app.runtime.jobs import TaskRecord
from app.server.main import create_app


def _fingerprint(seed: str) -> SourceFingerprint:
    return SourceFingerprint(
        kind="file",
        sha256=(seed * 64)[:64],
        byte_size=12,
        entry_count=1,
    )


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
            "measurements_by_case": {
                "shared.project_portability": {"duration_ms": 120}
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
    assert service.start_request.measurements_by_case == {
        "shared.project_portability": {"duration_ms": 120}
    }
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
    assert "outside the approved roots" in response.json()["detail"]
