from __future__ import annotations

import os
import shutil
import subprocess
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

    @property
    def metadata_path(self) -> Path:
        return self.root / "runtime.json"

    @property
    def source_dir(self) -> Path:
        return self.root / "source"


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
    if not runtime.metadata_path.is_file():
        return OmniVoiceRuntimeStatus(
            installed=False,
            message=(
                "Runtime đang được cài hoặc chưa hoàn tất. Hãy đợi cửa sổ cài đặt "
                "báo thành công."
            ),
            python_path=runtime.python_path,
        )

    probe = (
        "import importlib.util as u; "
        "missing=[n for n in ('torch','omnivoice','soundfile') if u.find_spec(n) is None]; "
        "print(','.join(missing)); raise SystemExit(1 if missing else 0)"
    )
    try:
        completed = subprocess.run(
            [str(runtime.python_path), "-c", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return OmniVoiceRuntimeStatus(
            installed=False,
            message=f"Không kiểm tra được OmniVoice runtime: {error}",
            python_path=runtime.python_path,
        )
    if completed.returncode != 0:
        missing = completed.stdout.strip() or "torch, omnivoice hoặc soundfile"
        return OmniVoiceRuntimeStatus(
            installed=False,
            message=(
                f"Runtime chưa hoàn tất; thiếu package: {missing}. "
                "Hãy chạy Cài / sửa runtime."
            ),
            python_path=runtime.python_path,
        )
    return OmniVoiceRuntimeStatus(
        installed=True,
        message=f"Runtime đã sẵn sàng: {runtime.python_path}",
        python_path=runtime.python_path,
    )


def remove_runtime_engine(runtime: OmniVoiceRuntime) -> None:
    for path in (
        runtime.root / ".venv",
        runtime.models_dir,
        runtime.cache_dir,
        runtime.source_dir,
    ):
        if path.is_dir():
            shutil.rmtree(path)
    runtime.metadata_path.unlink(missing_ok=True)


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
