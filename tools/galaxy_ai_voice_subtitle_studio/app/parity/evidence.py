"""Typed, content-bound evidence accepted by parity validators."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from .migration import MigrationDryRun
from .models import CheckResult, MediaExpectation


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
class RepositoryCheckEvidence:
    """Result produced internally by a Galaxy repository probe."""

    check_id: str
    status: str
    message: str
    measurements: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "measurements", MappingProxyType(dict(self.measurements)))


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
    app_version: str = ""

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
    return _result(
        check_id,
        "blocked",
        "Artifact requests must be resolved by a Galaxy repository probe",
    )


def judge_repository_evidence(
    check_id: str,
    evidence: RepositoryCheckEvidence,
) -> CheckResult:
    if evidence.check_id != check_id or evidence.status not in {"pass", "fail", "blocked"}:
        return _result(check_id, "fail", "Galaxy repository evidence is malformed")
    return _result(
        check_id,
        evidence.status,
        evidence.message,
        **evidence.measurements,
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
