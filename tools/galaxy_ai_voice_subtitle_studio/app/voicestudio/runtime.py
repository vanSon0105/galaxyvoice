from __future__ import annotations

import json
import os
import sys
import tempfile
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
            webview_data_dir=root / "webview" / "profile",
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
