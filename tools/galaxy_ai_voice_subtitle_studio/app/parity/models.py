"""Immutable domain records for native parity validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TypeAlias


ThresholdValue: TypeAlias = bool | int | float | str


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
