from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..common.paths import repository_root, studio_root


VOICESTUDIO_LICENSE = "AGPL-3.0-only"
DEFAULT_BACKEND_URL = "http://127.0.0.1:3900"
DEFAULT_FRONTEND_URL = "http://127.0.0.1:3901"


@dataclass(frozen=True)
class VoiceStudioRuntime:
    source_dir: Path
    installer_path: Path
    backend_url: str = DEFAULT_BACKEND_URL
    frontend_url: str = DEFAULT_FRONTEND_URL
    executable_override: Path | None = None
    program_files: Path | None = None
    local_app_data: Path | None = None

    @classmethod
    def from_repository(
        cls,
        root: Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "VoiceStudioRuntime":
        env = os.environ if environ is None else environ
        repository = Path(root) if root is not None else repository_root()
        override = env.get("VOICESTUDIO_EXECUTABLE", "").strip()
        program_files = env.get("ProgramFiles", "").strip()
        local_app_data = env.get("LOCALAPPDATA", "").strip()
        return cls(
            source_dir=repository / "omnivoicestudio",
            installer_path=studio_root() / "install_voicestudio.ps1",
            backend_url=env.get("VOICESTUDIO_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/"),
            frontend_url=env.get("VOICESTUDIO_FRONTEND_URL", DEFAULT_FRONTEND_URL).rstrip("/"),
            executable_override=Path(override).expanduser() if override else None,
            program_files=Path(program_files) if program_files else None,
            local_app_data=Path(local_app_data) if local_app_data else None,
        )

    def executable_candidates(self) -> tuple[Path, ...]:
        candidates: list[Path] = []
        if self.executable_override is not None:
            candidates.append(self.executable_override)
        if self.program_files is not None:
            candidates.append(self.program_files / "VoiceStudio" / "VoiceStudio.exe")
        if self.local_app_data is not None:
            candidates.extend(
                (
                    self.local_app_data / "Programs" / "VoiceStudio" / "VoiceStudio.exe",
                    self.local_app_data / "VoiceStudio" / "VoiceStudio.exe",
                )
            )
        candidates.extend(
            (
                self.source_dir
                / "frontend"
                / "src-tauri"
                / "target"
                / "release"
                / "omnivoice-studio.exe",
                self.source_dir
                / "frontend"
                / "src-tauri"
                / "target"
                / "release"
                / "VoiceStudio.exe",
            )
        )
        return tuple(dict.fromkeys(path.resolve() for path in candidates))


@dataclass(frozen=True)
class VoiceStudioRuntimeStatus:
    source_present: bool
    source_ready: bool
    installed: bool
    backend_online: bool
    version: str
    license_id: str
    executable: Path | None
    missing_tools: tuple[str, ...]
    launch_mode: str
    message: str


def inspect_runtime(
    runtime: VoiceStudioRuntime,
    *,
    probe_backend: bool = True,
) -> VoiceStudioRuntimeStatus:
    metadata = _source_metadata(runtime.source_dir)
    source_present = metadata is not None
    version = str(metadata.get("version", "unknown")) if metadata else "unknown"
    license_id = str(metadata.get("license", VOICESTUDIO_LICENSE)) if metadata else VOICESTUDIO_LICENSE
    executable = next((path for path in runtime.executable_candidates() if path.is_file()), None)
    missing_tools = tuple(
        label
        for command, label in (("bun", "Bun"), ("uv", "uv"))
        if shutil.which(command) is None
    )
    source_ready = source_present and not missing_tools
    online = backend_available(runtime.backend_url) if probe_backend else False

    if executable is not None:
        launch_mode = "installed"
        message = f"VoiceStudio {version} đã sẵn sàng"
    elif online:
        launch_mode = "backend"
        message = "Backend VoiceStudio đang chạy"
    elif source_ready:
        launch_mode = "source"
        message = f"Source VoiceStudio {version} đã sẵn sàng"
    elif source_present:
        launch_mode = "unavailable"
        message = "Thiếu runtime source: " + ", ".join(missing_tools)
    else:
        launch_mode = "unavailable"
        message = "Không tìm thấy VoiceStudio"

    return VoiceStudioRuntimeStatus(
        source_present=source_present,
        source_ready=source_ready,
        installed=executable is not None,
        backend_online=online,
        version=version,
        license_id=license_id,
        executable=executable,
        missing_tools=missing_tools,
        launch_mode=launch_mode,
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


def _source_metadata(source_dir: Path) -> dict[str, object] | None:
    package_path = source_dir / "frontend" / "package.json"
    try:
        payload = json.loads(package_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
