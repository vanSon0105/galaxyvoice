from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.parity import CaseResult, CheckResult
from app.parity.repository import (
    AcceptanceRecord,
    ImmutableRunError,
    ManualAnswer,
    ManualItem,
    ParityRepository,
    ParityRun,
)


def _running_run(root: Path, *, run_id: str = "run-1") -> ParityRun:
    return ParityRun(
        run_id=run_id,
        task_id="task-1",
        status="running",
        catalogue_version="catalogue-v1",
        catalogue_hash="a" * 64,
        manifest_path=str(root / "manifest.json"),
        manifest_hash="b" * 64,
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


def _pass_result() -> CaseResult:
    return CaseResult(
        case_id="studio.short_tts",
        status="pass",
        checks=(CheckResult("duration", "pass", "Within threshold"),),
    )


def test_repository_persists_terminal_envelope_and_separate_overlays(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    repository.create_run(_running_run(tmp_path))
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


def test_terminal_automated_results_cannot_be_rewritten(tmp_path: Path) -> None:
    repository = ParityRepository(tmp_path)
    repository.create_run(_running_run(tmp_path))
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
    repository.create_run(_running_run(tmp_path))
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
    repository.create_run(_running_run(tmp_path))

    repository.write_reports("run-1", b'{"run_id":"run-1"}\n', "# Run run-1\n")

    assert repository.read_report("run-1", "json") == b'{"run_id":"run-1"}\n'
    assert repository.read_report("run-1", "markdown") == b"# Run run-1\n"
    with pytest.raises(ValueError, match="format"):
        repository.read_report("run-1", "html")
