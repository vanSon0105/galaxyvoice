from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from app.parity import CaseResult, CheckResult
from app.parity.reports import render_reports
from app.parity.repository import ManualAnswer, ManualItem, ParityRun


def _fixed_run() -> ParityRun:
    return ParityRun(
        run_id="fixed-run",
        task_id="native-parity-validation_1234",
        status="completed",
        catalogue_version="2026-08-30",
        catalogue_hash="a" * 64,
        manifest_path=str(Path.home() / "private" / "manifest.json"),
        manifest_hash="b" * 64,
        manifest_snapshot_path="inputs/manifest.json",
        app_version="15.0",
        created_at="2026-08-30T10:00:00+00:00",
        completed_at="2026-08-30T10:05:00+00:00",
        report_json_path="reports/fixed-run.json",
        report_markdown_path="reports/fixed-run.md",
        required_case_ids=("studio.short_tts",),
        manual_items=(
            ManualItem(
                item_id="studio.short_tts.manual.1",
                case_id="studio.short_tts",
                prompt="Confirm output",
                required=True,
            ),
        ),
        thresholds={"studio.short_tts": {"duration_absolute_ms": 250}},
        case_results=(
            CaseResult(
                case_id="studio.short_tts",
                status="fail",
                checks=(
                    CheckResult(
                        check_id="duration",
                        status="fail",
                        message="Authorization: Bearer secret-token",
                        measurements={
                            "api_key": "secret-token",
                            "source": str(Path.home() / "voice.wav"),
                        },
                    ),
                ),
            ),
        ),
        warnings=("token=secret-token",),
        manual_answers={
            "studio.short_tts.manual.1": ManualAnswer(
                item_id="studio.short_tts.manual.1",
                accepted=False,
                note="password=secret-token",
                answered_at="2026-08-30T10:06:00+00:00",
            )
        },
    )


def test_reports_are_canonical_deterministic_and_redacted() -> None:
    first = render_reports(_fixed_run())
    second = render_reports(_fixed_run())

    assert first.json_bytes == second.json_bytes
    assert first.markdown == second.markdown
    assert first.json_bytes.endswith(b"\n")
    assert b"secret-token" not in first.json_bytes
    assert "secret-token" not in first.markdown
    assert str(Path.home()) not in first.markdown
    assert json.loads(first.json_bytes)["run_id"] == "fixed-run"


def test_markdown_has_stable_case_check_and_manual_evidence_order() -> None:
    report = render_reports(_fixed_run()).markdown

    assert report.index("studio.short_tts") < report.index("duration")
    assert report.index("duration") < report.index("studio.short_tts.manual.1")
    assert "Final acceptance: Not accepted" in report


def test_canonical_json_normalizes_unordered_and_non_finite_measurements() -> None:
    run = _fixed_run()
    check = replace(
        run.case_results[0].checks[0],
        measurements={
            "metric_names": frozenset({"wall", "ram", "vram"}),
            "invalid_metric": float("nan"),
            "consent_audio": b"raw-consent-audio",
            "selected_path": Path.home() / "private" / "voice.wav",
        },
    )
    run = replace(
        run,
        case_results=(replace(run.case_results[0], checks=(check,)),),
    )

    payload = json.loads(render_reports(run).json_bytes)
    measurements = payload["case_results"][0]["checks"][0]["measurements"]

    assert measurements["metric_names"] == ["ram", "vram", "wall"]
    assert measurements["invalid_metric"] == "nan"
    assert measurements["consent_audio"] == "<binary:17 bytes>"
    assert measurements["selected_path"] == "<home>\\private\\voice.wav"
    assert b"raw-consent-audio" not in render_reports(run).json_bytes
