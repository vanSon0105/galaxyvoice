from __future__ import annotations

import os
import json
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from app.parity import CaseResult, CheckResult
from app.parity.repository import (
    AcceptanceRecord,
    ImmutableRunError,
    ManualAnswer,
    ManualItem,
    ParityRepository,
    ParityRepositoryError,
    ParityRun,
)

MANIFEST_BYTES = b'{"schema_version":1,"corpus_id":"test","created_at":"fixed","cases":[]}\n'


def _running_run(root: Path, *, run_id: str = "run-1") -> ParityRun:
    return ParityRun(
        run_id=run_id,
        task_id="task-1",
        status="running",
        catalogue_version="catalogue-v1",
        catalogue_hash="a" * 64,
        manifest_path=str(root / "manifest.json"),
        manifest_hash=sha256(MANIFEST_BYTES).hexdigest(),
        manifest_snapshot_path="inputs/manifest.json",
        app_version="15.0",
        created_at="2026-08-30T10:00:00+00:00",
        report_json_path=f"reports/{run_id}.json",
        report_markdown_path=f"reports/{run_id}.md",
        required_case_ids=("studio.short_tts",),
        manual_items=(
            ManualItem(
                item_id="studio.short_tts.manual.1",
                case_id="studio.short_tts",
                prompt="Listen to the native take.",
                required=True,
            ),
        ),
        thresholds={"studio.short_tts": {"duration_absolute_ms": 250}},
    )


def _create(repository: ParityRepository, run: ParityRun) -> ParityRun:
    source = Path(run.manifest_path)
    if source.parent.is_dir() and not source.exists():
        source.write_bytes(MANIFEST_BYTES)
    return repository.create_run(run, manifest_bytes=MANIFEST_BYTES)


def _pass_result() -> CaseResult:
    return CaseResult(
        case_id="studio.short_tts",
        status="pass",
        checks=(CheckResult("duration", "pass", "Within threshold"),),
    )


def test_repository_persists_terminal_envelope_and_separate_overlays(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path))
    completed = repository.finish_run(
        "run-1",
        status="completed",
        case_results=(_pass_result(),),
        warnings=("review locally",),
        completed_at="2026-08-30T10:05:00+00:00",
    )

    repository.record_manual_answer(
        "run-1",
        ManualAnswer(
            item_id="studio.short_tts.manual.1",
            accepted=True,
            note="Listened",
            answered_at="2026-08-30T10:06:00+00:00",
        ),
    )
    repository.record_acceptance(
        "run-1",
        AcceptanceRecord(
            note="Approved",
            accepted_at="2026-08-30T10:07:00+00:00",
            catalogue_hash=completed.catalogue_hash,
            manifest_hash=completed.manifest_hash,
        ),
    )

    restored = ParityRepository(tmp_path).get_run("run-1")

    assert restored is not None
    assert restored.status == "completed"
    assert restored.case_results == (_pass_result(),)
    assert restored.manual_answers["studio.short_tts.manual.1"].note == "Listened"
    assert restored.acceptance is not None
    assert restored.acceptance.note == "Approved"
    assert (tmp_path / "runs" / "run-1" / "run.json").is_file()
    assert (tmp_path / "runs" / "run-1" / "manual.json").is_file()
    assert (tmp_path / "runs" / "run-1" / "acceptance.json").is_file()


def test_run_envelope_never_persists_absolute_selected_manifest_path(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path / "state")
    source_path = tmp_path / "private" / "manifest.json"
    source_path.parent.mkdir()
    run = _running_run(source_path.parent)

    stored = _create(repository, run)
    envelope = (repository.root / "runs" / run.run_id / "run.json").read_text(
        encoding="utf-8"
    )

    assert stored.manifest_path == "<selected-manifest>"
    assert str(source_path.parent.resolve()) not in envelope
    assert json.loads(envelope)["manifest_path"] == "<selected-manifest>"


def test_terminal_automated_results_cannot_be_rewritten(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path))
    repository.finish_run(
        "run-1",
        status="completed",
        case_results=(_pass_result(),),
        warnings=(),
        completed_at="2026-08-30T10:05:00+00:00",
    )

    with pytest.raises(ImmutableRunError):
        repository.finish_run(
            "run-1",
            status="completed",
            case_results=(CaseResult("studio.short_tts", "blocked", ()),),
            warnings=(),
            completed_at="2026-08-30T10:08:00+00:00",
        )

    assert repository.get_run("run-1").case_results == (_pass_result(),)  # type: ignore[union-attr]


def test_atomic_overlay_replace_failure_preserves_previous_answer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path))
    repository.finish_run(
        "run-1",
        status="completed",
        case_results=(_pass_result(),),
        warnings=(),
        completed_at="2026-08-30T10:05:00+00:00",
    )
    first = ManualAnswer(
        item_id="studio.short_tts.manual.1",
        accepted=True,
        note="first",
        answered_at="2026-08-30T10:06:00+00:00",
    )
    repository.record_manual_answer("run-1", first)

    def fail_replace(_source: os.PathLike[str], _destination: os.PathLike[str]) -> None:
        raise PermissionError("simulated replace failure")

    monkeypatch.setattr("app.parity.repository.os.replace", fail_replace)
    with pytest.raises(PermissionError, match="simulated replace failure"):
        repository.record_manual_answer(
            "run-1",
            ManualAnswer(
                item_id=first.item_id,
                accepted=False,
                note="second",
                answered_at="2026-08-30T10:07:00+00:00",
            ),
        )

    restored = ParityRepository(tmp_path).get_run("run-1")
    assert restored is not None
    assert restored.manual_answers[first.item_id] == first
    assert not tuple((tmp_path / "runs" / "run-1").glob("*.tmp"))


def test_reports_are_written_atomically_and_read_by_format(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path))

    repository.write_reports("run-1", b'{"run_id":"run-1"}\n', "# Run run-1\n")

    assert repository.read_report("run-1", "json") == b'{"run_id":"run-1"}\n'
    assert repository.read_report("run-1", "markdown") == b"# Run run-1\n"
    with pytest.raises(ValueError, match="format"):
        repository.read_report("run-1", "html")


def test_finish_cannot_rewrite_checkpointed_case_content(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path))
    checkpointed = CaseResult(
        "studio.short_tts",
        "fail",
        (CheckResult("duration", "fail", "old evidence"),),
    )
    repository.record_case_result("run-1", checkpointed)

    with pytest.raises(ImmutableRunError, match="checkpointed"):
        repository.finish_run(
            "run-1",
            status="completed",
            case_results=(
                CaseResult(
                    "studio.short_tts",
                    "pass",
                    (CheckResult("duration", "pass", "rewritten"),),
                ),
            ),
            warnings=(),
            completed_at="2026-08-30T10:05:00+00:00",
        )

    assert repository.get_run("run-1").case_results == (checkpointed,)  # type: ignore[union-attr]


def test_report_pair_reader_never_observes_mixed_revision_after_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path))
    repository.write_reports("run-1", b'{"revision":1}\n', "revision 1\n")
    original_replace = os.replace

    def fail_markdown(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        if Path(destination).name == "report.md":
            raise PermissionError("markdown replace failed")
        original_replace(source, destination)

    monkeypatch.setattr("app.parity.repository.os.replace", fail_markdown)
    with pytest.raises(PermissionError, match="markdown replace failed"):
        repository.write_reports("run-1", b'{"revision":2}\n', "revision 2\n")

    assert repository.read_report("run-1", "json") == b'{"revision":1}\n'
    assert repository.read_report("run-1", "markdown") == b"revision 1\n"


def test_list_runs_skips_corrupt_run_and_keeps_independent_evidence(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path, run_id="good"))
    corrupt = tmp_path / "runs" / "bad"
    corrupt.mkdir(parents=True)
    (corrupt / "run.json").write_text("{truncated", encoding="utf-8")

    assert [run.run_id for run in repository.list_runs()] == ["good"]
    assert repository.get_run("bad") is None


def test_list_runs_skips_semantically_invalid_check_status(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path, run_id="good"))
    _create(repository, _running_run(tmp_path, run_id="bad"))
    repository.finish_run(
        "bad",
        status="completed",
        case_results=(_pass_result(),),
        warnings=(),
        completed_at="2026-08-30T10:05:00+00:00",
    )
    path = tmp_path / "runs" / "bad" / "run.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["case_results"][0]["checks"][0]["status"] = "trusted-anyway"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert repository.get_run("bad") is None
    assert [run.run_id for run in repository.list_runs()] == ["good"]


def test_duplicate_manual_overlay_is_corrupt_and_unavailable(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path))
    repository.finish_run(
        "run-1",
        status="completed",
        case_results=(_pass_result(),),
        warnings=(),
        completed_at="2026-08-30T10:05:00+00:00",
    )
    duplicate = {
        "schema_version": 1,
        "answers": [
            {
                "item_id": "studio.short_tts.manual.1",
                "accepted": True,
                "note": "first",
                "answered_at": "2026-08-30T10:06:00+00:00",
            },
            {
                "item_id": "studio.short_tts.manual.1",
                "accepted": False,
                "note": "second",
                "answered_at": "2026-08-30T10:07:00+00:00",
            },
        ],
    }
    (tmp_path / "runs" / "run-1" / "manual.json").write_text(
        json.dumps(duplicate),
        encoding="utf-8",
    )

    assert repository.get_run("run-1") is None
    assert repository.list_runs() == ()


def test_malformed_acceptance_overlay_is_corrupt_and_unavailable(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path))
    repository.finish_run(
        "run-1",
        status="completed",
        case_results=(_pass_result(),),
        warnings=(),
        completed_at="2026-08-30T10:05:00+00:00",
    )
    malformed = {
        "schema_version": 1,
        "acceptance": {
            "note": "",
            "accepted_at": "2026-08-30T10:07:00+00:00",
            "catalogue_hash": "not-a-hash",
            "manifest_hash": "not-a-hash",
            "run_revision": "not-a-hash",
            "manual_revision": "not-a-hash",
            "input_revision": "not-a-hash",
        },
    }
    (tmp_path / "runs" / "run-1" / "acceptance.json").write_text(
        json.dumps(malformed),
        encoding="utf-8",
    )

    assert repository.get_run("run-1") is None
    assert repository.list_runs() == ()


def test_acceptance_compare_and_commit_rejects_changed_manual_revision(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path))
    completed = repository.finish_run(
        "run-1",
        status="completed",
        case_results=(_pass_result(),),
        warnings=(),
        completed_at="2026-08-30T10:05:00+00:00",
    )
    repository.record_manual_answer(
        "run-1",
        ManualAnswer(
            "studio.short_tts.manual.1",
            True,
            "first",
            "2026-08-30T10:06:00+00:00",
        ),
    )
    snapshot = repository.acceptance_snapshot("run-1")
    repository.record_manual_answer(
        "run-1",
        ManualAnswer(
            "studio.short_tts.manual.1",
            False,
            "changed",
            "2026-08-30T10:07:00+00:00",
        ),
    )

    with pytest.raises(ImmutableRunError, match="changed"):
        repository.commit_acceptance(
            snapshot,
            AcceptanceRecord(
                note="approved",
                accepted_at="2026-08-30T10:08:00+00:00",
                catalogue_hash=completed.catalogue_hash,
                manifest_hash=completed.manifest_hash,
            ),
            json_bytes=b"{}",
            markdown="report",
        )


def test_acceptance_snapshot_rejects_mutated_run_owned_manifest(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    _create(repository, _running_run(tmp_path))
    repository.manifest_snapshot_path("run-1").write_bytes(b"changed")

    with pytest.raises(ImmutableRunError, match="manifest"):
        repository.acceptance_snapshot("run-1")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction probe")
def test_run_and_report_paths_reject_privilege_free_junctions(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path / "state")
    runs = repository.root / "runs"
    reports = repository.root / "reports"
    outside_run = tmp_path / "outside-run"
    outside_report = tmp_path / "outside-report"
    for path in (runs, reports, outside_run, outside_report):
        path.mkdir(parents=True, exist_ok=True)

    run_junction = runs / "evil"
    report_junction = reports / "evil"
    for junction, target in ((run_junction, outside_run), (report_junction, outside_report)):
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"Junctions are unavailable: {result.stderr or result.stdout}")

    try:
        with pytest.raises((ValueError, ParityRepositoryError), match="link|reparse|confined"):
            _create(repository, _running_run(repository.root, run_id="evil"))
        assert not (outside_run / "run.json").exists()
        assert repository.list_runs() == ()

        _create(repository, _running_run(repository.root, run_id="safe"))
        # Replace the normal report run directory with a junction before writing.
        safe_report_dir = reports / "safe"
        safe_report_dir.mkdir(parents=True, exist_ok=True)
        safe_report_dir.rmdir()
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(safe_report_dir), str(outside_report)],
            capture_output=True,
            check=True,
        )
        with pytest.raises((ValueError, ParityRepositoryError), match="link|reparse|confined"):
            repository.write_reports("safe", b"{}\n", "safe\n")
        assert not (outside_report / "current.json").exists()
    finally:
        for junction in (run_junction, report_junction, reports / "safe"):
            if junction.exists():
                os.rmdir(junction)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction probe")
def test_repository_rejects_junction_in_existing_ancestor_before_root_creation(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    state_link = tmp_path / "state-link"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(state_link), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"Junctions are unavailable: {result.stderr or result.stdout}")

    try:
        repository = ParityRepository(state_link / "parity")
        with pytest.raises((ValueError, ParityRepositoryError), match="link|reparse"):
            _create(repository, _running_run(repository.root))
        assert not (outside / "parity" / "runs" / "run-1" / "run.json").exists()
    finally:
        if state_link.exists():
            os.rmdir(state_link)
