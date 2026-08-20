from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import webbrowser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..common.processes import managed_media_processes, terminate_process_tree
from .runtime import (
    VoiceStudioRuntime,
    backend_available,
    frontend_available,
    inspect_runtime,
)


class VoiceStudioController:
    def __init__(self, runtime: VoiceStudioRuntime) -> None:
        self.runtime = runtime
        self.process: subprocess.Popen[Any] | None = None
        self.installer_process: subprocess.Popen[Any] | None = None
        self._lock = threading.RLock()
        self._generation = 0

    def launch(self) -> str:
        with self._lock:
            status = inspect_runtime(self.runtime)
            if status.backend_online and frontend_available(self.runtime.backend_url):
                return "attached"
            if not status.installed:
                details = ", ".join(status.missing_components) or "runtime cần cập nhật"
                raise RuntimeError(
                    f"VoiceStudio chưa sẵn sàng ({details}). Hãy bấm 'Cài runtime local'."
                )
            if self._process_is_running():
                return "local"

            self.runtime.ensure_directories()
            parsed = urlparse(self.runtime.backend_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 3900
            command = [
                str(self.runtime.python_path),
                "-m",
                "uvicorn",
                "main:app",
                "--app-dir",
                str(self.runtime.source_dir / "backend"),
                "--host",
                host,
                "--port",
                str(port),
            ]
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "OMNIVOICE_PROJECT_ROOT": str(self.runtime.source_dir),
                    "OMNIVOICE_DATA_DIR": str(self.runtime.data_dir),
                    "OMNIVOICE_CACHE_DIR": str(self.runtime.cache_dir),
                    "HF_HOME": str(self.runtime.cache_dir),
                    "OMNIVOICE_MCP_DISABLE": "1",
                    "OMNIVOICE_ANALYTICS_DISABLED": "1",
                }
            )
            with self.runtime.backend_log_path.open("a", encoding="utf-8") as log_file:
                process = subprocess.Popen(
                    command,
                    cwd=str(self.runtime.source_dir),
                    env=environment,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=_background_creation_flags(),
                )
            self._replace_process(process)
            return "local"

    def wait_until_ready(
        self,
        *,
        timeout: float = 240.0,
        poll_interval: float = 0.75,
    ) -> bool:
        with self._lock:
            generation = self._generation
            process = self.process
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if backend_available(self.runtime.backend_url) and frontend_available(
                self.runtime.backend_url
            ):
                return True
            with self._lock:
                if generation != self._generation:
                    return False
            if process is not None and process.poll() is not None:
                return False
            time.sleep(poll_interval)
        return False

    def open_browser(self) -> None:
        if not frontend_available(self.runtime.backend_url):
            raise RuntimeError("Giao diện VoiceStudio local chưa sẵn sàng.")
        webbrowser.open(self.runtime.backend_url)

    def disable_upstream_analytics(self, *, timeout: float = 5.0) -> None:
        request = Request(
            f"{self.runtime.backend_url}/api/settings/analytics",
            data=json.dumps({"enabled": False}).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="PUT",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                status = int(response.status)
        except (HTTPError, URLError, OSError, TimeoutError, ValueError) as error:
            raise RuntimeError(
                "Không thể tắt thống kê VoiceStudio trước khi mở giao diện."
            ) from error
        if not 200 <= status < 300:
            raise RuntimeError(
                f"Không thể tắt thống kê VoiceStudio (HTTP {status})."
            )

    def run_installer(self) -> subprocess.Popen[Any]:
        if self.installer_running():
            return self.installer_process  # type: ignore[return-value]
        if not self.runtime.installer_path.is_file():
            raise RuntimeError(f"Không tìm thấy bộ cài local: {self.runtime.installer_path}")
        if not self.runtime.snapshot_metadata_path.is_file():
            raise RuntimeError(f"Không tìm thấy snapshot VoiceStudio: {self.runtime.snapshot_dir}")
        if not self.runtime.webview_wheel.is_file():
            raise RuntimeError(f"Không tìm thấy WebView wheel: {self.runtime.webview_wheel}")

        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.runtime.installer_path),
                "-SnapshotRoot",
                str(self.runtime.snapshot_dir),
                "-RuntimeRoot",
                str(self.runtime.root),
                "-NonInteractive",
            ],
            cwd=str(self.runtime.installer_path.parent),
            creationflags=_installer_creation_flags(),
        )
        self.installer_process = process
        managed_media_processes.add(process)
        return process

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            process = self.process
            self.process = None
        if process is None:
            return
        managed_media_processes.discard(process)
        terminate_process_tree(process)

    def stop_installer(self) -> None:
        process = self.installer_process
        self.installer_process = None
        if process is None:
            return
        managed_media_processes.discard(process)
        if process.poll() is None:
            terminate_process_tree(process)

    def finish_installer(self, process: subprocess.Popen[Any]) -> None:
        managed_media_processes.discard(process)
        if self.installer_process is process:
            self.installer_process = None

    def stop_all(self) -> None:
        self.stop()
        self.stop_installer()

    def is_running(self) -> bool:
        with self._lock:
            return self._process_is_running()

    def installer_running(self) -> bool:
        return self.installer_process is not None and self.installer_process.poll() is None

    def backend_log_tail(self, *, max_chars: int = 4000) -> str:
        return self._log_tail(self.runtime.backend_log_path, max_chars=max_chars)

    def installer_log_tail(self, *, max_chars: int = 4000) -> str:
        return self._log_tail(self.runtime.installer_log_path, max_chars=max_chars)

    @staticmethod
    def _log_tail(path: os.PathLike[str], *, max_chars: int) -> str:
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as log_file:
                content = log_file.read()
        except OSError:
            return ""
        return content[-max_chars:].strip()

    def _replace_process(self, process: subprocess.Popen[Any]) -> None:
        previous = self.process
        self._generation += 1
        self.process = process
        managed_media_processes.add(process)
        if previous is not None and previous is not process:
            managed_media_processes.discard(previous)
            terminate_process_tree(previous)

    def _process_is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None


def _background_creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _installer_creation_flags() -> int:
    return getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
