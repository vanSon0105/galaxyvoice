from __future__ import annotations

from dataclasses import dataclass

from ..runtime.capabilities import PreflightCheck


@dataclass(frozen=True)
class DiskSpaceCheck:
    path: str
    total_bytes: int
    available_bytes: int
    required_bytes: int
    reserve_bytes: int
    ready: bool
    message: str


@dataclass(frozen=True)
class OperationAudit:
    capability_id: str
    ready: bool
    state: str
    requested_device: str
    resolved_device: str
    fallback_used: bool
    recommended_model_id: str
    message: str
    checks: tuple[PreflightCheck, ...]
    disk: DiskSpaceCheck | None = None


@dataclass(frozen=True)
class SystemReport:
    cpu_count: int
    total_memory_bytes: int
    nvidia_gpu: bool
    cuda_device_count: int
    recommended_device: str
    disks: tuple[DiskSpaceCheck, ...]
    log_path: str
