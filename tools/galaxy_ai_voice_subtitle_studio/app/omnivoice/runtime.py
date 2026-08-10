from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


AUTO_DEVICE = "auto"
CUDA_DEVICE = "cuda"
XPU_DEVICE = "xpu"
CPU_DEVICE = "cpu"
OMNIVOICE_DEVICES = (AUTO_DEVICE, CUDA_DEVICE, XPU_DEVICE, CPU_DEVICE)
DEVICE_LABELS = {
    AUTO_DEVICE: "Tự động",
    CUDA_DEVICE: "NVIDIA CUDA",
    XPU_DEVICE: "Intel Arc XPU",
    CPU_DEVICE: "CPU",
}
DEVICE_CODES = {label: code for code, label in DEVICE_LABELS.items()}


@dataclass(frozen=True)
class OmniVoiceRuntime:
    root: Path
    python_path: Path
    models_dir: Path
    profiles_dir: Path
    cache_dir: Path

    @classmethod
    def from_base(cls, base: Path) -> "OmniVoiceRuntime":
        root = Path(base) / "GalaxyAIStudio" / "models" / "OmniVoice"
        return cls(
            root=root,
            python_path=root / ".venv" / "Scripts" / "python.exe",
            models_dir=root / "checkpoints",
            profiles_dir=root / "voices",
            cache_dir=root / "cache",
        )

    @classmethod
    def default(cls) -> "OmniVoiceRuntime":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            base = Path(local_app_data)
        else:
            try:
                base = Path.home() / "AppData" / "Local"
            except RuntimeError:
                base = Path(tempfile.gettempdir())
        return cls.from_base(base)

    def ensure_directories(self) -> None:
        for path in (self.root, self.models_dir, self.profiles_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class OmniVoiceRuntimeStatus:
    installed: bool
    message: str
    python_path: Path


def inspect_runtime(runtime: OmniVoiceRuntime) -> OmniVoiceRuntimeStatus:
    if not runtime.python_path.is_file():
        return OmniVoiceRuntimeStatus(
            installed=False,
            message=f"Runtime chưa được cài: {runtime.python_path}",
            python_path=runtime.python_path,
        )
    return OmniVoiceRuntimeStatus(
        installed=True,
        message=f"Runtime đã sẵn sàng: {runtime.python_path}",
        python_path=runtime.python_path,
    )


def remove_runtime_engine(runtime: OmniVoiceRuntime) -> None:
    for path in (runtime.root / ".venv", runtime.models_dir, runtime.cache_dir):
        if path.is_dir():
            shutil.rmtree(path)
    metadata_path = runtime.root / "runtime.json"
    metadata_path.unlink(missing_ok=True)


def clear_model_cache(runtime: OmniVoiceRuntime) -> None:
    for path in (runtime.models_dir, runtime.cache_dir):
        if path.is_dir():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)


def normalize_omnivoice_device(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized in OMNIVOICE_DEVICES:
        return normalized
    if value in DEVICE_CODES:
        return DEVICE_CODES[value]
    return AUTO_DEVICE


def omnivoice_device_label(code: str) -> str:
    return DEVICE_LABELS[normalize_omnivoice_device(code)]
