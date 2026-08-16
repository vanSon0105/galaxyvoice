from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..common.paths import repository_root


VOICESTUDIO_LICENSE = "AGPL-3.0-only"
VOICESTUDIO_SNAPSHOT_VERSION = "0.4.2"
DEFAULT_BACKEND_URL = "http://127.0.0.1:3900"
WEBVIEW_PACKAGE = "tkwry"
WEBVIEW_PROFILE_DIRECTORY = "profile"
_PROFILE_OWNER_FILE = ".galaxy-owner.json"


@dataclass(frozen=True)
class VoiceStudioRuntime:
    snapshot_dir: Path
    root: Path
    source_dir: Path
    python_path: Path
    data_dir: Path
    cache_dir: Path
    logs_dir: Path
    webview_site_packages: Path
    webview_data_dir: Path
    webview_wheel: Path
    installer_path: Path
    backend_url: str = DEFAULT_BACKEND_URL

    @classmethod
    def from_repository(
        cls,
        repository: Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "VoiceStudioRuntime":
        env = os.environ if environ is None else environ
        repo = Path(repository) if repository is not None else repository_root()
        tool_root = repo / "tools" / "galaxy_ai_voice_subtitle_studio"
        snapshot_dir = tool_root / "vendor" / "voicestudio"
        metadata = _read_json(snapshot_dir / "SNAPSHOT.json") or {}
        version = str(metadata.get("version") or VOICESTUDIO_SNAPSHOT_VERSION)

        runtime_override = str(env.get("VOICESTUDIO_RUNTIME_ROOT", "")).strip()
        if runtime_override:
            root = Path(runtime_override).expanduser()
        else:
            local_app_data = str(env.get("LOCALAPPDATA", "")).strip()
            base = Path(local_app_data) if local_app_data else _default_local_app_data()
            root = base / "GalaxyAIStudio" / "models" / "VoiceStudio"

        return cls(
            snapshot_dir=snapshot_dir,
            root=root,
            source_dir=root / "sources" / version,
            python_path=root / ".venv" / "Scripts" / "python.exe",
            data_dir=root / "data",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
            webview_site_packages=root / "webview" / "site-packages",
            webview_data_dir=root / "webview" / WEBVIEW_PROFILE_DIRECTORY,
            webview_wheel=(
                tool_root
                / "vendor"
                / "wheels"
                / "tkwry-0.1.4-cp310-abi3-win_amd64.whl"
            ),
            installer_path=tool_root / "install_voicestudio.ps1",
            backend_url=str(env.get("VOICESTUDIO_BACKEND_URL", DEFAULT_BACKEND_URL)).rstrip("/"),
        )

    @property
    def metadata_path(self) -> Path:
        return self.root / "runtime.json"

    @property
    def backend_log_path(self) -> Path:
        return self.logs_dir / "backend.log"

    @property
    def installer_log_path(self) -> Path:
        return self.logs_dir / "install.log"

    @property
    def snapshot_metadata_path(self) -> Path:
        return self.snapshot_dir / "SNAPSHOT.json"

    def ensure_directories(self) -> None:
        for path in (
            self.root,
            self.data_dir,
            self.cache_dir,
            self.logs_dir,
            self.webview_site_packages,
            self.webview_data_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass
class WebViewProfileLease:
    data_directory: Path
    owner_path: Path
    token: str
    recovered: bool = False
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        owner = _read_json(self.owner_path)
        if owner is None or str(owner.get("token") or "") != self.token:
            return
        try:
            self.owner_path.unlink(missing_ok=True)
        except OSError:
            pass


def acquire_webview_profile(
    runtime: VoiceStudioRuntime,
    *,
    process_id: int | None = None,
) -> WebViewProfileLease:
    """Claim the persistent WebView profile or isolate this launch after a crash.

    WebView2 can block the Tk thread indefinitely when another process still
    owns the same data directory. A recovery profile keeps the current launch
    responsive while preserving the normal persistent profile for clean runs.
    """

    runtime.ensure_directories()
    pid = os.getpid() if process_id is None else int(process_id)
    lease = _try_claim_profile(runtime.webview_data_dir, pid=pid, recovered=False)
    if lease is not None:
        return lease

    persistent_owner_path = _profile_owner_path(runtime.webview_data_dir)
    owner = _read_json(persistent_owner_path) or {}
    owner_pid = _positive_int(owner.get("pid"))
    if (
        owner_pid is None
        or (
            not _process_is_running(owner_pid)
            and not _webview_child_is_running(owner_pid)
        )
    ):
        try:
            persistent_owner_path.unlink(missing_ok=True)
        except OSError:
            pass

    recovery_root = runtime.webview_data_dir.parent / "recovery-profiles"
    for _attempt in range(10):
        token = uuid.uuid4().hex
        recovery_dir = recovery_root / f"session-{pid}-{token[:8]}"
        _clone_profile(runtime.webview_data_dir, recovery_dir)
        lease = _try_claim_profile(
            recovery_dir,
            pid=pid,
            recovered=True,
            token=token,
        )
        if lease is not None:
            return lease
    raise RuntimeError("Không thể tạo profile WebView2 riêng cho phiên hiện tại.")


def _clone_profile(source: Path, destination: Path) -> None:
    """Best-effort warm clone; volatile WebView cache files may be locked."""

    destination.mkdir(parents=True, exist_ok=True)
    if not source.is_dir():
        return
    for source_path in source.rglob("*"):
        if source_path.name == _PROFILE_OWNER_FILE:
            continue
        try:
            relative_path = source_path.relative_to(source)
            destination_path = destination / relative_path
            if source_path.is_dir():
                destination_path.mkdir(parents=True, exist_ok=True)
            elif source_path.is_file():
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination_path)
        except OSError:
            continue


def _try_claim_profile(
    directory: Path,
    *,
    pid: int,
    recovered: bool,
    token: str | None = None,
) -> WebViewProfileLease | None:
    directory.mkdir(parents=True, exist_ok=True)
    owner_path = _profile_owner_path(directory)
    lease_token = token or uuid.uuid4().hex
    try:
        descriptor = os.open(owner_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pid": pid, "token": lease_token}, stream)
    except Exception:
        try:
            owner_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return WebViewProfileLease(
        data_directory=directory,
        owner_path=owner_path,
        token=lease_token,
        recovered=recovered,
    )


def _profile_owner_path(directory: Path) -> Path:
    return directory.parent / f".{directory.name}{_PROFILE_OWNER_FILE}"


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _process_is_running(process_id: int) -> bool:
    if process_id == os.getpid():
        return True
    if sys.platform == "win32":
        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        )
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel32.OpenProcess(synchronize, False, process_id)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _webview_child_is_running(owner_process_id: int) -> bool:
    if sys.platform != "win32" or owner_process_id <= 0:
        return False
    script = (
        "$p=Get-CimInstance Win32_Process -Filter \"ParentProcessId="
        f"{owner_process_id}\" -ErrorAction SilentlyContinue | "
        "Where-Object Name -eq 'msedgewebview2.exe' | Select-Object -First 1; "
        "if($p){'1'}"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    return completed.returncode == 0 and completed.stdout.strip() == "1"


@dataclass(frozen=True)
class VoiceStudioRuntimeStatus:
    snapshot_present: bool
    runtime_installed: bool
    webview_installed: bool
    backend_online: bool
    update_required: bool
    version: str
    license_id: str
    python_path: Path
    source_dir: Path
    missing_components: tuple[str, ...]
    message: str

    @property
    def installed(self) -> bool:
        return self.runtime_installed and self.webview_installed and not self.update_required


def inspect_runtime(
    runtime: VoiceStudioRuntime,
    *,
    probe_backend: bool = True,
) -> VoiceStudioRuntimeStatus:
    snapshot_metadata = _read_json(runtime.snapshot_metadata_path) or {}
    version = str(snapshot_metadata.get("version") or VOICESTUDIO_SNAPSHOT_VERSION)
    license_id = str(snapshot_metadata.get("license") or VOICESTUDIO_LICENSE)
    snapshot_present = _source_ready(runtime.snapshot_dir)
    installed_metadata = _read_json(runtime.metadata_path) or {}
    installed_version = str(installed_metadata.get("snapshot_version") or "")
    update_required = bool(installed_version and installed_version != version)
    runtime_installed = (
        runtime.python_path.is_file()
        and runtime.metadata_path.is_file()
        and _source_ready(runtime.source_dir)
    )
    webview_installed = (
        (runtime.webview_site_packages / WEBVIEW_PACKAGE / "__init__.py").is_file()
        and (runtime.webview_site_packages / WEBVIEW_PACKAGE / "_core.pyd").is_file()
    )
    backend_online = backend_available(runtime.backend_url) if probe_backend else False

    missing: list[str] = []
    if not snapshot_present:
        missing.append("snapshot VoiceStudio")
    if not runtime_installed:
        missing.append("Python runtime")
    if not webview_installed:
        missing.append("WebView bridge")

    if update_required:
        message = f"Có snapshot VoiceStudio {version} mới; hãy cập nhật runtime local"
    elif backend_online:
        message = f"VoiceStudio {version} đang chạy trong Galaxy"
    elif runtime_installed and webview_installed:
        message = f"VoiceStudio {version} đã sẵn sàng"
    elif snapshot_present:
        message = "Chưa cài runtime local: " + ", ".join(missing)
    else:
        message = "Thiếu snapshot VoiceStudio đi kèm Galaxy"

    return VoiceStudioRuntimeStatus(
        snapshot_present=snapshot_present,
        runtime_installed=runtime_installed,
        webview_installed=webview_installed,
        backend_online=backend_online,
        update_required=update_required,
        version=version,
        license_id=license_id,
        python_path=runtime.python_path,
        source_dir=runtime.source_dir,
        missing_components=tuple(missing),
        message=message,
    )


def backend_available(base_url: str, *, timeout: float = 0.8) -> bool:
    request = Request(
        f"{base_url.rstrip('/')}/system/info",
        headers={"Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 300
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        return False


def frontend_available(base_url: str, *, timeout: float = 0.8) -> bool:
    request = Request(base_url.rstrip("/") + "/", headers={"Accept": "text/html"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 400
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        return False


def load_webview_class(runtime: VoiceStudioRuntime) -> type[Any]:
    site_packages = str(runtime.webview_site_packages.resolve())
    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)
    try:
        from tkwry import WebView
    except (ImportError, OSError) as error:
        raise RuntimeError(
            "WebView nhúng chưa sẵn sàng. Hãy bấm 'Cài runtime local' rồi thử lại."
        ) from error
    return WebView


def _source_ready(source_dir: Path) -> bool:
    required = (
        source_dir / "pyproject.toml",
        source_dir / "backend" / "main.py",
        source_dir / "omnivoice" / "__init__.py",
        source_dir / "frontend" / "dist" / "index.html",
        source_dir / "LICENSE",
    )
    return all(path.is_file() for path in required)


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _default_local_app_data() -> Path:
    try:
        return Path.home() / "AppData" / "Local"
    except RuntimeError:
        return Path(tempfile.gettempdir())
