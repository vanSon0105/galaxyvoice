from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..common.errors import TaskCancelledError
from ..common.diagnostics import redact_sensitive_text, redacted_binary_log
from ..common.processes import managed_media_processes, terminate_process_tree
from ..reliability.service import guard_output_space


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


def install_omnivoice_runtime(
    runtime: OmniVoiceRuntime,
    installer: Path,
    *,
    device: str = AUTO_DEVICE,
    progress: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
    task_id: str | None = None,
) -> dict[str, str]:
    """Install the isolated runtime as a cancellable, disk-guarded operation."""

    script = Path(installer).expanduser()
    if not script.is_file():
        raise FileNotFoundError(f"Không tìm thấy bộ cài: {script}")
    report = progress or (lambda _message: None)
    guard_output_space(runtime.root, minimum_mib=5 * 1024)
    if stop_event is not None and stop_event.is_set():
        raise TaskCancelledError()

    report("Đang cài OmniVoice runtime...")
    runtime.ensure_directories()
    log_path = runtime.root / "install.log"
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Device",
        normalize_omnivoice_device(device),
        "-NonInteractive",
    ]
    try:
        with redacted_binary_log(log_path) as log_stream:
            process = subprocess.Popen(
                command,
                cwd=str(script.parent),
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            managed_media_processes.add(process, task_id=task_id)
            try:
                while process.poll() is None:
                    if stop_event is not None and stop_event.wait(0.25):
                        if task_id:
                            managed_media_processes.terminate_task(task_id)
                        else:
                            terminate_process_tree(process)
                        raise TaskCancelledError()
                if process.returncode != 0:
                    log_stream.flush()
                    details = _installer_log_tail(log_path)
                    raise RuntimeError(
                        f"Cài OmniVoice runtime thất bại với mã {process.returncode}."
                        + (f"\n{details}" if details else f" Xem log: {log_path}")
                    )
            finally:
                managed_media_processes.discard(process)
    except OSError as error:
        raise RuntimeError(f"Không mở được bộ cài OmniVoice: {error}") from error

    status = inspect_runtime(runtime)
    if not status.installed:
        raise RuntimeError(status.message)
    report("OmniVoice runtime đã sẵn sàng.")
    return {
        "python_path": str(status.python_path),
        "message": status.message,
        "log_path": str(log_path),
    }


def _installer_log_tail(path: Path, limit: int = 2_000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return redact_sensitive_text(raw.decode("utf-8", errors="replace")[-max(1, int(limit)):].strip())


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


def inspect_runtime_devices(runtime: OmniVoiceRuntime) -> tuple[str, ...]:
    """Return accelerators that the isolated OmniVoice torch can actually use."""
    probe = (
        "import torch; available=['cpu']; "
        "available.insert(0,'cuda') if torch.cuda.is_available() else None; "
        "xpu=getattr(torch,'xpu',None); "
        "available.insert(0,'xpu') if xpu is not None and xpu.is_available() else None; "
        "print(','.join(available))"
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
    except (OSError, subprocess.TimeoutExpired):
        return (CPU_DEVICE,)
    if completed.returncode != 0:
        return (CPU_DEVICE,)
    detected = tuple(
        item for item in completed.stdout.strip().split(",") if item in OMNIVOICE_DEVICES
    )
    return detected or (CPU_DEVICE,)


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


def load_supported_language_ids(runtime: OmniVoiceRuntime) -> tuple[str, ...]:
    workspace_map = Path(__file__).resolve().parents[4] / "omnivoice" / "docs" / "lang_id_name_map.tsv"
    bundled_map = (
        Path(__file__).resolve().parents[2]
        / "vendor"
        / "voicestudio"
        / "docs"
        / "lang_id_name_map.tsv"
    )
    candidates = (
        runtime.source_dir / "docs" / "lang_id_name_map.tsv",
        bundled_map,
        workspace_map,
    )
    for path in candidates:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        language_ids = tuple(
            line.split("\t", 1)[0].strip()
            for line in lines[1:]
            if line.strip() and "\t" in line
        )
        if language_ids:
            return (*language_ids, "auto")
    return ()
