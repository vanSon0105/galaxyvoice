"""Immutable domain records for native parity validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from pathlib import Path
from typing import Literal, Mapping, TypeAlias


ThresholdValue: TypeAlias = bool | int | float | str
AssetStatus: TypeAlias = Literal[
    "ready",
    "missing",
    "checksum_mismatch",
    "unsupported",
    "unsafe_path",
]
CheckStatus: TypeAlias = Literal[
    "pass",
    "fail",
    "blocked",
    "manual_pending",
    "not_applicable",
]
ASSET_STATUSES = frozenset(
    {"ready", "missing", "checksum_mismatch", "unsupported", "unsafe_path"}
)
CHECK_STATUSES = frozenset(
    {"pass", "fail", "blocked", "manual_pending", "not_applicable"}
)


@dataclass(frozen=True)
class ParityCase:
    case_id: str
    area: str
    title: str
    required: bool
    fixture_roles: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    manual_prompts: tuple[str, ...] = ()
    thresholds: Mapping[str, ThresholdValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fixture_roles", tuple(self.fixture_roles))
        object.__setattr__(self, "checks", tuple(self.checks))
        object.__setattr__(self, "manual_prompts", tuple(self.manual_prompts))
        object.__setattr__(
            self,
            "thresholds",
            MappingProxyType(dict(self.thresholds)),
        )


@dataclass(frozen=True)
class ParityCatalogue:
    version: str
    cases: tuple[ParityCase, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))


@dataclass(frozen=True)
class SourceFingerprint:
    kind: str
    sha256: str
    byte_size: int
    entry_count: int


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


@dataclass(frozen=True)
class MediaExpectation:
    extension: str | None = None
    container: str | None = None
    audio_codec: str | None = None
    video_codec: str | None = None
    audio_streams: int | None = None
    video_streams: int | None = None
    subtitle_streams: int | None = None
    channels: int | None = None
    sample_rate: int | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True)
class ManifestAsset:
    role: str
    path: str
    sha256: str
    byte_size: int
    media: MediaExpectation | None = None


@dataclass(frozen=True)
class ManifestCase:
    case_id: str
    assets: tuple[ManifestAsset, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "assets", tuple(self.assets))


@dataclass(frozen=True)
class ParityFixtureManifest:
    schema_version: int
    corpus_id: str
    created_at: str
    cases: tuple[ManifestCase, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))


@dataclass(frozen=True)
class MediaInfo:
    container: str
    audio_codec: str | None = None
    video_codec: str | None = None
    audio_streams: int = 0
    video_streams: int = 0
    subtitle_streams: int = 0
    channels: int | None = None
    sample_rate: int | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True)
class AssetInspection:
    role: str
    path: Path | None
    status: AssetStatus
    findings: tuple[Finding, ...] = ()
    media: MediaInfo | None = None

    def __post_init__(self) -> None:
        if self.status not in ASSET_STATUSES:
            raise ValueError(f"Unknown asset status: {self.status}")
        object.__setattr__(self, "findings", tuple(self.findings))


@dataclass(frozen=True)
class CorpusInspection:
    manifest: ParityFixtureManifest
    assets_by_role: Mapping[str, AssetInspection]
    roles_by_case: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assets_by_role",
            MappingProxyType(dict(self.assets_by_role)),
        )
        object.__setattr__(
            self,
            "roles_by_case",
            MappingProxyType(
                {case_id: tuple(roles) for case_id, roles in self.roles_by_case.items()}
            ),
        )


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    status: CheckStatus
    message: str
    measurements: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in CHECK_STATUSES:
            raise ValueError(f"Unknown check status: {self.status}")
        object.__setattr__(
            self,
            "measurements",
            MappingProxyType(dict(self.measurements)),
        )


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    status: CheckStatus
    checks: tuple[CheckResult, ...]

    def __post_init__(self) -> None:
        if self.status not in CHECK_STATUSES:
            raise ValueError(f"Unknown check status: {self.status}")
        object.__setattr__(self, "checks", tuple(self.checks))
