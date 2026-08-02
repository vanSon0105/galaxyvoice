from __future__ import annotations

import shutil
import subprocess

AUTO_DEVICE = "auto"
CPU_DEVICE = "cpu"
CUDA_DEVICE = "cuda"
PROCESSING_DEVICES = (AUTO_DEVICE, CPU_DEVICE, CUDA_DEVICE)

PROCESSING_DEVICE_LABELS = {
    AUTO_DEVICE: "Tự động",
    CPU_DEVICE: "CPU (không dùng GPU)",
    CUDA_DEVICE: "NVIDIA GPU rời",
}
PROCESSING_DEVICE_CODES = {label: code for code, label in PROCESSING_DEVICE_LABELS.items()}


def normalize_processing_device(value: str) -> str:
    normalized = str(value).strip().lower()
    return normalized if normalized in PROCESSING_DEVICES else AUTO_DEVICE


def processing_device_label(code: str) -> str:
    return PROCESSING_DEVICE_LABELS[normalize_processing_device(code)]


def processing_device_code(label_or_code: str) -> str:
    if label_or_code in PROCESSING_DEVICE_CODES:
        return PROCESSING_DEVICE_CODES[label_or_code]
    return normalize_processing_device(label_or_code)


def detect_cuda_device_count() -> int:
    try:
        import ctranslate2

        return max(0, int(ctranslate2.get_cuda_device_count()))
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return 0


def detect_nvidia_hardware() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False
    try:
        completed = subprocess.run(
            [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and bool(completed.stdout.strip())


def resolve_torch_device(
    processing_device: str,
    *,
    nvidia_available: bool | None = None,
) -> str:
    selected = normalize_processing_device(processing_device)
    if selected == CPU_DEVICE:
        return CPU_DEVICE
    has_nvidia = detect_nvidia_hardware() if nvidia_available is None else nvidia_available
    if has_nvidia:
        return CUDA_DEVICE
    if selected == CUDA_DEVICE:
        raise RuntimeError(
            "NVIDIA GPU with CUDA was not detected. Choose Auto or CPU on this machine."
        )
    return CPU_DEVICE


def resolve_whisper_runtime(
    processing_device: str,
    *,
    cuda_device_count: int | None = None,
) -> tuple[str, str]:
    selected = normalize_processing_device(processing_device)
    if selected == CPU_DEVICE:
        return "cpu", "int8"

    available_cuda = (
        detect_cuda_device_count()
        if cuda_device_count is None
        else max(0, int(cuda_device_count))
    )
    if available_cuda > 0:
        return "cuda", "float16"
    if selected == CUDA_DEVICE:
        raise RuntimeError(
            "NVIDIA GPU with CUDA was not detected. Choose Auto or CPU on this machine."
        )
    return "cpu", "int8"
