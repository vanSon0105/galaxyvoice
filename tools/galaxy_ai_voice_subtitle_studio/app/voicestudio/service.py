from __future__ import annotations

import os
import shutil
import subprocess
import time
import webbrowser
from typing import Any

from ..common.processes import managed_media_processes, terminate_process_tree
from .runtime import VoiceStudioRuntime, backend_available, frontend_available, inspect_runtime


class VoiceStudioController:
    def __init__(self, runtime: VoiceStudioRuntime) -> None:
        self.runtime = runtime
        self.process: subprocess.Popen[Any] | None = None

    def launch(self) -> str:
        status = inspect_runtime(self.runtime)
        if status.executable is not None:
            if self.is_running():
                return "installed"
            self._replace_process(
                subprocess.Popen(
                    [str(status.executable)],
                    cwd=str(status.executable.parent),
                    creationflags=_desktop_creation_flags(),
                )
            )
            return "installed"
        if status.backend_online and frontend_available(self.runtime.frontend_url):
            webbrowser.open(self.runtime.frontend_url)
            return "browser"
        if status.source_ready:
            return self.launch_source()
        raise RuntimeError(
            "VoiceStudio chưa sẵn sàng. Hãy cài VoiceStudio bản đầy đủ hoặc cài Bun và uv để chạy source."
        )

    def launch_source(self) -> str:
        if self.is_running():
            return "source"
        if not self.runtime.source_dir.is_dir():
            raise RuntimeError(f"Không tìm thấy source VoiceStudio: {self.runtime.source_dir}")
        bun = shutil.which("bun")
        uv = shutil.which("uv")
        missing = [label for value, label in ((bun, "Bun"), (uv, "uv")) if value is None]
        if missing:
            raise RuntimeError("Thiếu runtime để chạy source VoiceStudio: " + ", ".join(missing))
        self._replace_process(
            subprocess.Popen(
                [str(bun), "run", "dev"],
                cwd=str(self.runtime.source_dir),
                creationflags=_source_creation_flags(),
            )
        )
        return "source"

    def open_browser(self) -> None:
        if not backend_available(self.runtime.backend_url) or not frontend_available(
            self.runtime.frontend_url
        ):
            raise RuntimeError("Giao diện VoiceStudio chưa sẵn sàng.")
        webbrowser.open(self.runtime.frontend_url)

    def wait_for_source_ready(
        self,
        *,
        timeout: float = 900.0,
        poll_interval: float = 1.0,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if backend_available(self.runtime.backend_url) and frontend_available(
                self.runtime.frontend_url
            ):
                return True
            if self.process is not None and self.process.poll() is not None:
                return False
            time.sleep(poll_interval)
        return False

    def run_installer(self) -> subprocess.Popen[Any]:
        installer = self.runtime.installer_path
        if not installer.is_file():
            raise RuntimeError(f"Không tìm thấy bộ cài VoiceStudio: {installer}")
        return subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(installer),
            ],
            cwd=str(installer.parent),
            creationflags=_installer_creation_flags(),
        )

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        managed_media_processes.discard(process)
        terminate_process_tree(process)

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _replace_process(self, process: subprocess.Popen[Any]) -> None:
        self.stop()
        self.process = process
        managed_media_processes.add(process)


def _desktop_creation_flags() -> int:
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0


def _source_creation_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


def _installer_creation_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
