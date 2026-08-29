from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
from collections import deque
from pathlib import Path

from ..common.compute import detect_cuda_device_count, detect_nvidia_hardware
from ..common.diagnostics import default_log_path, redact_sensitive_text
from ..common.ffmpeg import find_ffprobe
from ..runtime.capabilities import (
    CapabilityRegistry,
    PreflightCheck,
    PreflightRequest,
    PreflightResult,
)
from .models import DiskSpaceCheck, OperationAudit, SystemReport


MIB = 1024 * 1024
GIB = 1024 * MIB
DEFAULT_DISK_RESERVE_BYTES = 512 * MIB


class InsufficientDiskSpaceError(RuntimeError):
    def __init__(self, check: DiskSpaceCheck) -> None:
        self.check = check
        super().__init__(check.message)


def ensure_disk_space(
    path: Path,
    *,
    required_bytes: int,
    reserve_bytes: int = DEFAULT_DISK_RESERVE_BYTES,
) -> DiskSpaceCheck:
    target = _nearest_existing(Path(path).expanduser())
    usage = shutil.disk_usage(target)
    required = max(0, int(required_bytes))
    reserve = max(0, int(reserve_bytes))
    ready = int(usage.free) >= required + reserve
    if ready:
        message = (
            f"Còn {_format_bytes(usage.free)} trên {target}; "
            f"tác vụ cần khoảng {_format_bytes(required)}."
        )
    else:
        message = (
            f"Không đủ dung lượng trống trên {target}. Còn {_format_bytes(usage.free)}, "
            f"cần ít nhất {_format_bytes(required + reserve)} gồm vùng dự phòng. "
            "Hãy đổi thư mục xuất hoặc giải phóng dung lượng rồi thử lại."
        )
    check = DiskSpaceCheck(
        path=str(target.resolve()),
        total_bytes=int(usage.total),
        available_bytes=int(usage.free),
        required_bytes=required,
        reserve_bytes=reserve,
        ready=ready,
        message=message,
    )
    if not ready:
        raise InsufficientDiskSpaceError(check)
    return check


def estimate_required_bytes(
    source_paths: tuple[Path, ...] = (),
    *,
    minimum_bytes: int = 256 * MIB,
    multiplier: float = 1.5,
) -> int:
    source_bytes = 0
    for path in source_paths:
        try:
            source_bytes += path.stat().st_size
        except OSError:
            continue
    return max(int(minimum_bytes), int(source_bytes * max(0.0, multiplier)))


def estimate_audio_bytes(
    text: str,
    *,
    output_count: int = 1,
    minimum_bytes: int = 128 * MIB,
) -> int:
    """Estimate working space for generated speech and its encoded outputs."""

    # Conversational speech averages roughly 12 characters/second. A 48 kHz
    # mono PCM working file uses 96 KB/second; the extra factor covers segments,
    # manifests, and optional encoded copies retained during assembly.
    per_character = 8_000 * max(1, int(output_count))
    return max(int(minimum_bytes), len(text.strip()) * per_character * 2)


def estimate_media_working_bytes(
    source_paths: tuple[Path, ...],
    *,
    sample_rate: int = 48_000,
    channels: int = 2,
    bytes_per_sample: int = 4,
    working_copies: int = 2,
    minimum_bytes: int = 512 * MIB,
    fallback_multiplier: float = 8.0,
) -> int:
    """Estimate decoded PCM plus intermediate/output copies for media work."""

    durations = [
        duration
        for duration in (_probe_media_duration_seconds(path) for path in source_paths)
        if duration > 0
    ]
    fallback = estimate_required_bytes(
        source_paths,
        minimum_bytes=minimum_bytes,
        multiplier=fallback_multiplier,
    )
    if not durations:
        return fallback
    decoded_seconds = sum(durations) + max(durations) * max(1, int(working_copies))
    pcm_bytes = decoded_seconds * max(8_000, int(sample_rate))
    pcm_bytes *= max(1, int(channels)) * max(1, int(bytes_per_sample))
    return max(fallback, int(pcm_bytes), int(minimum_bytes))


def estimate_video_working_bytes(
    source_paths: tuple[Path, ...],
    *,
    duration_seconds: float,
    width: int,
    height: int,
    fps: float,
    minimum_bytes: int = 1024 * MIB,
) -> int:
    """Estimate encoded video output plus muxing/intermediate working space."""

    # A conservative H.264 estimate. The clamp avoids absurd values for tiny
    # previews while still reserving enough room for 2K/60 exports.
    pixels_per_second = max(1, int(width)) * max(1, int(height)) * max(1.0, float(fps))
    estimated_mbps = min(100.0, max(8.0, pixels_per_second * 0.075 / 1_000_000))
    encoded_bytes = max(0.0, float(duration_seconds)) * estimated_mbps * 1_000_000 / 8
    source_floor = estimate_required_bytes(
        source_paths,
        minimum_bytes=minimum_bytes,
        multiplier=2.0,
    )
    return max(source_floor, int(encoded_bytes * 1.75), int(minimum_bytes))


def _probe_media_duration_seconds(path: Path) -> float:
    ffprobe = find_ffprobe()
    if not ffprobe:
        return 0.0
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            return 0.0
        payload = json.loads(completed.stdout or "{}")
        return max(0.0, float((payload.get("format") or {}).get("duration", 0)))
    except (OSError, subprocess.TimeoutExpired, TypeError, ValueError, json.JSONDecodeError):
        return 0.0


def guard_output_space(
    output_path: str | Path,
    *,
    source_paths: tuple[Path, ...] = (),
    minimum_mib: int = 256,
    multiplier: float = 1.5,
    required_bytes: int | None = None,
) -> DiskSpaceCheck:
    required = required_bytes
    if required is None:
        required = estimate_required_bytes(
            source_paths,
            minimum_bytes=max(1, minimum_mib) * MIB,
            multiplier=multiplier,
        )
    return ensure_disk_space(Path(output_path or "."), required_bytes=required)


def read_diagnostic_log(*, limit: int = 200, path: Path | None = None) -> list[str]:
    log_path = path or default_log_path()
    bounded_limit = min(1_000, max(1, int(limit)))
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as stream:
            lines = deque(stream, maxlen=bounded_limit)
    except OSError:
        return []
    return [redact_sensitive_text(line.rstrip("\r\n")) for line in lines]


class ReliabilityService:
    def __init__(self, capabilities: CapabilityRegistry) -> None:
        self.capabilities = capabilities

    def system_report(self, disk_paths: tuple[Path, ...] = ()) -> SystemReport:
        nvidia = detect_nvidia_hardware()
        cuda_count = detect_cuda_device_count()
        disks: list[DiskSpaceCheck] = []
        seen: set[str] = set()
        for raw_path in disk_paths:
            target = _nearest_existing(Path(raw_path).expanduser())
            key = str(target.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            usage = shutil.disk_usage(target)
            disks.append(
                DiskSpaceCheck(
                    path=str(target.resolve()),
                    total_bytes=int(usage.total),
                    available_bytes=int(usage.free),
                    required_bytes=0,
                    reserve_bytes=DEFAULT_DISK_RESERVE_BYTES,
                    ready=int(usage.free) >= DEFAULT_DISK_RESERVE_BYTES,
                    message=f"Còn {_format_bytes(usage.free)} trên {target}.",
                )
            )
        return SystemReport(
            cpu_count=max(1, int(os.cpu_count() or 1)),
            total_memory_bytes=_total_memory_bytes(),
            nvidia_gpu=nvidia,
            cuda_device_count=cuda_count,
            recommended_device="cuda" if nvidia and cuda_count > 0 else "cpu",
            disks=tuple(disks),
            log_path=str(default_log_path()),
        )

    def audit(
        self,
        request: PreflightRequest,
        *,
        output_path: str = "",
        required_disk_bytes: int = 0,
    ) -> OperationAudit:
        try:
            result = self.capabilities.preflight(request)
        except Exception as error:
            message = redact_sensitive_text(str(error) or type(error).__name__)
            result = PreflightResult.unavailable(
                request.capability_id,
                requested_device=request.device,
                message=message,
                checks=(
                    PreflightCheck(
                        code="runtime-probe",
                        state="error",
                        message=message,
                        remediation="Kiểm tra runtime/model rồi thử lại.",
                    ),
                ),
            )
        try:
            descriptor = self.capabilities.get(request.capability_id)
            supports_cuda = "cuda" in descriptor.devices
            kind = descriptor.kind
        except KeyError:
            supports_cuda = False
            kind = ""
        checks = list(result.checks)
        checks.append(
            PreflightCheck(
                code="capability",
                state="ready" if result.ready else "error",
                message=result.message or ("Runtime sẵn sàng." if result.ready else "Runtime chưa sẵn sàng."),
                remediation="" if result.ready else "Mở phần cài runtime/model rồi chạy kiểm tra lại.",
            )
        )
        fallback_used = (
            request.device == "auto"
            and supports_cuda
            and result.resolved_device == "cpu"
        )
        if fallback_used:
            checks.append(
                PreflightCheck(
                    code="device-fallback",
                    state="warning",
                    message="Không dùng được CUDA; tác vụ sẽ chạy bằng CPU và có thể chậm hơn.",
                    remediation="Cài CUDA runtime phù hợp hoặc tiếp tục với CPU.",
                )
            )
        disk: DiskSpaceCheck | None = None
        disk_ready = True
        if output_path and required_disk_bytes > 0:
            try:
                disk = ensure_disk_space(
                    Path(output_path),
                    required_bytes=required_disk_bytes,
                )
            except InsufficientDiskSpaceError as error:
                disk = error.check
                disk_ready = False
            checks.append(
                PreflightCheck(
                    code="disk-space",
                    state="ready" if disk.ready else "error",
                    message=disk.message,
                    remediation="" if disk.ready else "Đổi thư mục xuất hoặc giải phóng dung lượng.",
                )
            )
        recommendation = _recommended_model(request.capability_id, kind, result.resolved_device)
        ready = result.ready and disk_ready
        return OperationAudit(
            capability_id=request.capability_id,
            ready=ready,
            state="ready" if ready and not fallback_used else "warning" if ready else "unavailable",
            requested_device=request.device,
            resolved_device=result.resolved_device,
            fallback_used=fallback_used,
            recommended_model_id=recommendation,
            message=result.message,
            checks=tuple(checks),
            disk=disk,
        )


def _recommended_model(capability_id: str, kind: str, device: str) -> str:
    if kind == "asr" or capability_id.startswith("asr."):
        return "medium" if device == "cuda" else "base"
    if capability_id == "tts.omnivoice":
        return "k2-fsa/OmniVoice"
    if capability_id == "audio.separation":
        return "UVR-MDX-NET Inst HQ 3"
    return ""


def _nearest_existing(path: Path) -> Path:
    candidate = path.resolve(strict=False)
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    if candidate.exists():
        return candidate
    return Path.cwd().resolve()


def _total_memory_bytes() -> int:
    if os.name != "nt":
        return 0

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_phys", ctypes.c_ulonglong),
            ("available_phys", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_phys)
    except (AttributeError, OSError):
        pass
    return 0


def _format_bytes(value: int) -> str:
    amount = max(0, int(value))
    if amount >= GIB:
        return f"{amount / GIB:.1f} GB"
    return f"{amount / MIB:.0f} MB"
