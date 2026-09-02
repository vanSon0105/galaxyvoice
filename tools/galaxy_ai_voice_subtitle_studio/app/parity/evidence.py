"""Typed, content-bound evidence accepted by parity validators."""

from __future__ import annotations

import json
import math
import re
from hashlib import sha256
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..common.cache import stable_digest
from ..common.errors import TaskCancelledError
from .migration import MigrationDryRun
from .models import CheckResult, MediaExpectation
from .security import fingerprint_source


_SHA256 = re.compile(r"[0-9a-f]{64}")
_PRODUCER = "galaxy-ai-voice-subtitle-studio"
_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_ARTIFACT_READ_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class HardwareIdentity:
    platform: str
    architecture: str
    cpu_model: str
    logical_cpu_count: int
    memory_bytes: int
    accelerator_model: str = ""


@dataclass(frozen=True)
class ArtifactCheckEvidence:
    role: str
    sha256: str


@dataclass(frozen=True)
class MediaCheckEvidence:
    role: str
    expected: MediaExpectation


@dataclass(frozen=True)
class DurationCheckEvidence:
    native_seconds: float
    reference_seconds: float


@dataclass(frozen=True)
class SubtitleCueEvidence:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class SubtitleCheckEvidence:
    native: tuple[SubtitleCueEvidence, ...]
    reference: tuple[SubtitleCueEvidence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "native", tuple(self.native))
        object.__setattr__(self, "reference", tuple(self.reference))


@dataclass(frozen=True)
class IdentityCheckEvidence:
    native: Mapping[str, str]
    reference: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "native", MappingProxyType(dict(self.native)))
        object.__setattr__(self, "reference", MappingProxyType(dict(self.reference)))


@dataclass(frozen=True)
class LoudnessCheckEvidence:
    measured_lufs: float


@dataclass(frozen=True)
class PerformanceSample:
    wall_seconds: float | None
    peak_ram_bytes: int | None = None
    peak_vram_bytes: int | None = None
    response_ms: tuple[float, ...] = ()
    applicable_metrics: frozenset[str] = frozenset(
        {"wall_seconds", "peak_ram_bytes", "peak_vram_bytes"}
    )
    hardware_identity: HardwareIdentity | None = None
    resolved_device: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "response_ms", tuple(self.response_ms))
        object.__setattr__(self, "applicable_metrics", frozenset(self.applicable_metrics))


@dataclass(frozen=True)
class PerformanceCheckEvidence:
    native: PerformanceSample
    reference: PerformanceSample


@dataclass(frozen=True)
class CancellationCheckEvidence:
    acknowledgement_seconds: float
    device: str


@dataclass(frozen=True)
class RecoverySample:
    interrupted: bool
    task_status: str
    resumable: bool
    recovery_route: str | None = None


@dataclass(frozen=True)
class RecoveryCheckEvidence:
    sample: RecoverySample


@dataclass(frozen=True)
class MigrationCheckEvidence:
    source_roles: tuple[str, ...] = ()
    copied_source_confirmed: bool = False
    dry_runs: tuple[MigrationDryRun, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_roles", tuple(self.source_roles))
        object.__setattr__(self, "dry_runs", tuple(self.dry_runs))


def validate_hardware_identity(value: HardwareIdentity | None) -> bool:
    return bool(
        isinstance(value, HardwareIdentity)
        and value.platform.strip()
        and value.architecture.strip()
        and value.cpu_model.strip()
        and isinstance(value.logical_cpu_count, int)
        and not isinstance(value.logical_cpu_count, bool)
        and value.logical_cpu_count > 0
        and isinstance(value.memory_bytes, int)
        and not isinstance(value.memory_bytes, bool)
        and value.memory_bytes > 0
        and isinstance(value.accelerator_model, str)
    )


def hardware_payload(value: HardwareIdentity) -> dict[str, object]:
    return {
        "platform": value.platform,
        "architecture": value.architecture,
        "cpu_model": value.cpu_model,
        "logical_cpu_count": value.logical_cpu_count,
        "memory_bytes": value.memory_bytes,
        "accelerator_model": value.accelerator_model,
    }


def judge_artifact_evidence(
    case_id: str,
    check_id: str,
    evidence: ArtifactCheckEvidence,
    assets: Mapping[str, Path],
    *,
    check_cancelled: Callable[[], None] | None = None,
) -> CheckResult:
    if not isinstance(evidence, ArtifactCheckEvidence):
        return _result(check_id, "blocked", "Galaxy artifact evidence is required")
    if not evidence.role.strip() or not _SHA256.fullmatch(evidence.sha256):
        return _result(check_id, "fail", "Artifact evidence binding is malformed")
    artifact = assets.get(evidence.role)
    if artifact is None:
        return _result(check_id, "blocked", "Bound Galaxy artifact is unavailable")
    try:
        raw = _read_artifact_bytes(artifact, check_cancelled=check_cancelled)
        artifact_sha256 = sha256(raw).hexdigest()
        if artifact_sha256 != evidence.sha256:
            return _result(check_id, "fail", "Galaxy artifact checksum differs")
        payload = _strict_json(raw.decode("utf-8"))
        root = _exact_mapping(
            payload,
            {"schema_version", "producer", "case_id", "checks"},
            "artifact",
        )
        if root["schema_version"] != 1 or root["producer"] != _PRODUCER:
            return _result(check_id, "fail", "Artifact producer contract is invalid")
        if root["case_id"] != case_id:
            return _result(check_id, "fail", "Artifact case binding differs")
        checks = _mapping(root["checks"], "artifact checks")
        proof = _mapping(checks.get(check_id), f"artifact check {check_id}")
        _validate_proof(
            check_id,
            proof,
            assets,
            check_cancelled=check_cancelled,
        )
    except TaskCancelledError:
        raise
    except Exception as error:
        return _result(
            check_id,
            "fail",
            f"Galaxy artifact proof is invalid: {type(error).__name__}",
        )
    return _result(
        check_id,
        "pass",
        "Galaxy artifact proof is content-bound and valid",
        artifact_sha256=evidence.sha256,
        proof_kind=proof["kind"],
    )


def judge_migration_evidence(
    check_id: str,
    evidence: MigrationCheckEvidence,
) -> CheckResult:
    if (
        not isinstance(evidence, MigrationCheckEvidence)
        or evidence.copied_source_confirmed is not True
        or not evidence.dry_runs
    ):
        return _result(check_id, "blocked", "Galaxy migration dry-run evidence is required")
    reports = evidence.dry_runs
    if check_id == "source_immutability":
        passed = all(item.source_before == item.source_after for item in reports)
    elif check_id == "sandbox_cleanup":
        passed = all(item.sandbox_cleaned for item in reports)
    elif check_id == "consent_mapping":
        candidates = tuple(
            candidate
            for report in reports
            for group in (
                report.voice_profiles,
                report.persona_bundles,
            )
            for candidate in group
        )
        passed = bool(candidates) and all(
            isinstance(candidate.consent.confirmed, bool)
            and (
                not candidate.consent.confirmed
                or bool(
                    candidate.consent.statement.strip()
                    and candidate.consent.recorded_at.strip()
                    and candidate.consent.provenance.strip()
                )
            )
            for candidate in candidates
        )
    elif check_id == "missing_media":
        passed = all(
            asset.state in {"managed", "linked", "missing", "unsafe"}
            and (asset.state != "missing" or bool(asset.expected_sha256))
            for report in reports
            for asset in report.assets
        )
    else:
        return _result(check_id, "blocked", "No migration evidence judge is registered")
    return _result(
        check_id,
        "pass" if passed else "fail",
        "Galaxy migration dry-run evidence is valid"
        if passed
        else "Galaxy migration dry-run evidence failed policy validation",
        dry_run_count=len(reports),
        source_sha256=tuple(item.source_before.sha256 for item in reports),
    )


def _validate_proof(
    check_id: str,
    proof: Mapping[str, Any],
    assets: Mapping[str, Path],
    *,
    check_cancelled: Callable[[], None] | None,
) -> None:
    kind = proof.get("kind")
    if check_id in {"project_reopen", "moved_directory_portability"}:
        _require_fields(
            proof,
            {
                "kind",
                "before",
                "after",
                "before_sha256",
                "after_sha256",
                "before_location",
                "after_location",
            },
        )
        if kind != "repository_round_trip":
            raise ValueError("wrong proof kind")
        before = _mapping(proof["before"], "before project")
        after = _mapping(proof["after"], "after project")
        before_sha = _sha(proof["before_sha256"])
        after_sha = _sha(proof["after_sha256"])
        if stable_digest(before) != before_sha or stable_digest(after) != after_sha:
            raise ValueError("project digest mismatch")
        if before_sha != after_sha:
            raise ValueError("project content changed")
        if check_id == "moved_directory_portability" and (
            not isinstance(proof["before_location"], str)
            or not isinstance(proof["after_location"], str)
            or proof["before_location"] == proof["after_location"]
        ):
            raise ValueError("moved location evidence is missing")
        return
    if check_id == "missing_media_relink":
        _require_fields(
            proof,
            {
                "kind",
                "asset_id",
                "relinked_role",
                "expected_sha256",
                "relinked_sha256",
                "before_state",
                "after_state",
            },
        )
        relinked_role = proof["relinked_role"]
        if not isinstance(relinked_role, str) or not relinked_role.strip():
            raise ValueError("relinked role is missing")
        relinked_asset = assets.get(relinked_role)
        if relinked_asset is None:
            raise ValueError("relinked asset is unavailable")
        relinked_fingerprint = fingerprint_source(
            relinked_asset,
            check_cancelled=check_cancelled,
        )
        if (
            kind != "missing_media_relink"
            or not str(proof["asset_id"]).strip()
            or proof["before_state"] != "missing"
            or proof["after_state"] not in {"linked", "managed"}
            or _sha(proof["expected_sha256"]) != _sha(proof["relinked_sha256"])
            or relinked_fingerprint.kind != "file"
            or relinked_fingerprint.sha256 != proof["relinked_sha256"]
        ):
            raise ValueError("relink proof mismatch")
        return
    if check_id == "handoff_return":
        _require_fields(
            proof,
            {
                "kind",
                "handoff_id",
                "source",
                "returned",
                "source_sha256",
                "returned_sha256",
                "status",
            },
        )
        source = _mapping(proof["source"], "handoff source")
        returned = _mapping(proof["returned"], "handoff return")
        source_revision = source.get("revision")
        returned_revision = returned.get("revision")
        if (
            kind != "handoff_return"
            or proof["status"] != "returned"
            or not str(proof["handoff_id"]).strip()
            or stable_digest(source) != _sha(proof["source_sha256"])
            or stable_digest(returned) != _sha(proof["returned_sha256"])
            or source.get("project_id") != returned.get("project_id")
            or not _nonnegative_int(source_revision)
            or not _nonnegative_int(returned_revision)
            or int(returned_revision) <= int(source_revision)
        ):
            raise ValueError("handoff proof mismatch")
        return
    if check_id == "checkpoint_resume":
        _require_fields(
            proof,
            {
                "kind",
                "workflow_id",
                "checkpoint_sha256",
                "resumed_from_sha256",
                "completed_before",
                "completed_after",
            },
        )
        before = _string_sequence(proof["completed_before"])
        after = _string_sequence(proof["completed_after"])
        if (
            kind != "checkpoint_resume"
            or not str(proof["workflow_id"]).strip()
            or _sha(proof["checkpoint_sha256"])
            != _sha(proof["resumed_from_sha256"])
            or stable_digest({"completed": before}) != proof["checkpoint_sha256"]
            or not set(before).issubset(after)
            or len(after) <= len(before)
        ):
            raise ValueError("checkpoint proof mismatch")
        return

    _require_fields(
        proof,
        {"kind", "assertion_id", "expected_sha256", "observed_sha256"},
    )
    if (
        kind != "artifact_binding"
        or proof["assertion_id"] != check_id
        or _sha(proof["expected_sha256"]) != _sha(proof["observed_sha256"])
    ):
        raise ValueError("artifact binding proof mismatch")


def _read_artifact_bytes(
    path: Path,
    *,
    check_cancelled: Callable[[], None] | None,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    with path.open("rb") as source:
        while chunk := source.read(_ARTIFACT_READ_CHUNK_BYTES):
            if check_cancelled is not None:
                check_cancelled()
            total += len(chunk)
            if total > _MAX_ARTIFACT_BYTES:
                raise ValueError("artifact size limit exceeded")
            chunks.append(chunk)
    return b"".join(chunks)


def _strict_json(raw: str) -> Any:
    return json.loads(raw, object_pairs_hook=_strict_object)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def _exact_mapping(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    result = _mapping(value, label)
    _require_fields(result, fields)
    return result


def _require_fields(value: Mapping[str, Any], fields: set[str]) -> None:
    if set(value) != fields:
        raise ValueError("proof fields differ")


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError("invalid SHA-256")
    return value


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("expected string sequence")
    result = tuple(value)
    if not all(isinstance(item, str) and item for item in result):
        raise ValueError("expected string sequence")
    return result


def _result(
    check_id: str,
    status: str,
    message: str,
    **measurements: object,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        status=status,  # type: ignore[arg-type]
        message=message,
        measurements=MappingProxyType(dict(measurements)),
    )
