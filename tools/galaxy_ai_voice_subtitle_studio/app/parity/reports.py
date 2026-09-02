"""Canonical redacted JSON and deterministic Markdown parity reports."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .repository import ParityRun
from .security import redact_report_value


@dataclass(frozen=True)
class RenderedReports:
    json_bytes: bytes
    markdown: str


def render_reports(run: ParityRun) -> RenderedReports:
    payload = _json_value(redact_report_value(_report_payload(run)))
    json_bytes = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    return RenderedReports(json_bytes=json_bytes, markdown=_render_markdown(payload))


def _report_payload(run: ParityRun) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run.run_id,
        "task_id": run.task_id,
        "status": run.status,
        "catalogue_version": run.catalogue_version,
        "catalogue_hash": run.catalogue_hash,
        "manifest_hash": run.manifest_hash,
        "app_version": run.app_version,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "report_paths": {
            "json": run.report_json_path,
            "markdown": run.report_markdown_path,
        },
        "source_fingerprints": {
            key: _fingerprint_payload(value)
            for key, value in sorted(run.source_fingerprints.items())
        },
        "reference_fingerprints": {
            key: _fingerprint_payload(value)
            for key, value in sorted(run.reference_fingerprints.items())
        },
        "required_case_ids": list(run.required_case_ids),
        "thresholds": {
            case_id: dict(values)
            for case_id, values in sorted(run.thresholds.items())
        },
        "threshold_overrides": [
            {
                "case_id": item.case_id,
                "threshold_id": item.threshold_id,
                "catalogue_value": item.catalogue_value,
                "override_value": item.override_value,
                "provenance": item.provenance,
                "note": item.note,
                "relaxation": item.relaxation,
            }
            for item in run.threshold_overrides
        ],
        "case_results": [
            {
                "case_id": result.case_id,
                "status": result.status,
                "checks": [
                    {
                        "check_id": check.check_id,
                        "status": check.status,
                        "message": check.message,
                        "measurements": check.measurements,
                    }
                    for check in result.checks
                ],
            }
            for result in run.case_results
        ],
        "warnings": list(run.warnings),
        "manual_items": [
            {
                "item_id": item.item_id,
                "case_id": item.case_id,
                "prompt": item.prompt,
                "required": item.required,
                "answer": (
                    {
                        "accepted": answer.accepted,
                        "note": answer.note,
                        "answered_at": answer.answered_at,
                    }
                    if (answer := run.manual_answers.get(item.item_id)) is not None
                    else None
                ),
            }
            for item in run.manual_items
        ],
        "acceptance": (
            {
                "note": run.acceptance.note,
                "accepted_at": run.acceptance.accepted_at,
                "catalogue_hash": run.acceptance.catalogue_hash,
                "manifest_hash": run.acceptance.manifest_hash,
                "run_revision": run.acceptance.run_revision,
                "manual_revision": run.acceptance.manual_revision,
                "input_revision": run.acceptance.input_revision,
                "report_revision": run.acceptance.report_revision,
            }
            if run.acceptance is not None
            else None
        ),
    }


def _fingerprint_payload(value: Any) -> dict[str, object]:
    return {
        "kind": value.kind,
        "sha256": value.sha256,
        "byte_size": value.byte_size,
        "entry_count": value.entry_count,
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        normalized = [_json_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value).casefold()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<binary:{len(value)} bytes>"
    if isinstance(value, Path):
        return redact_report_value(str(value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return f"<unsupported:{type(value).__name__}>"


def _render_markdown(payload: Mapping[str, Any]) -> str:
    acceptance = payload.get("acceptance")
    lines = [
        f"# Native Parity Report: {_text(payload['run_id'])}",
        "",
        f"- Status: {_text(payload['status'])}",
        f"- Catalogue: {_text(payload['catalogue_version'])} (`{_text(payload['catalogue_hash'])}`)",
        f"- Manifest hash: `{_text(payload['manifest_hash'])}`",
        f"- App version: {_text(payload['app_version'])}",
        f"- Created: {_text(payload['created_at'])}",
        f"- Completed: {_text(payload.get('completed_at') or 'Not completed')}",
        f"- Final acceptance: {'Accepted' if acceptance else 'Not accepted'}",
        "",
        "## Cases",
    ]
    case_results = payload.get("case_results", [])
    if not case_results:
        lines.extend(("", "No completed case evidence."))
    for result in case_results:
        lines.extend(("", f"### {_text(result['case_id'])}: {_text(result['status'])}"))
        for check in result.get("checks", []):
            lines.append(
                f"- `{_text(check['check_id'])}` [{_text(check['status'])}]: "
                f"{_text(check['message'])}"
            )
            measurements = check.get("measurements", {})
            if measurements:
                rendered = json.dumps(
                    measurements,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                lines.append(f"  Measurements: `{_text(rendered)}`")
    lines.extend(("", "## Manual Acceptance"))
    manual_items = payload.get("manual_items", [])
    if not manual_items:
        lines.extend(("", "No manual acceptance items."))
    for item in manual_items:
        answer = item.get("answer")
        state = "pending" if answer is None else ("accepted" if answer["accepted"] else "rejected")
        lines.extend(
            (
                "",
                f"- `{_text(item['item_id'])}` [{state}]: {_text(item['prompt'])}",
            )
        )
        if answer is not None and answer.get("note"):
            lines.append(f"  Note: {_text(answer['note'])}")
    overrides = payload.get("threshold_overrides", [])
    if overrides:
        lines.extend(("", "## Threshold Overrides", ""))
        for item in overrides:
            kind = "relaxation" if item["relaxation"] else "tightening"
            lines.append(
                f"- `{_text(item['case_id'])}.{_text(item['threshold_id'])}` "
                f"[{kind}]: {_text(item['catalogue_value'])} -> "
                f"{_text(item['override_value'])}"
            )
            lines.append(f"  Provenance: {_text(item['provenance'])}")
            lines.append(f"  Note: {_text(item['note'])}")
    if acceptance:
        lines.extend(
            (
                "",
                "## Final Acceptance",
                "",
                f"- Accepted: {_text(acceptance['accepted_at'])}",
                f"- Note: {_text(acceptance['note'])}",
            )
        )
    warnings = payload.get("warnings", [])
    if warnings:
        lines.extend(("", "## Warnings", ""))
        lines.extend(f"- {_text(item)}" for item in warnings)
    return "\n".join(lines) + "\n"


def _text(value: Any) -> str:
    return str(value).replace("\r", " ").replace("\n", " ")
