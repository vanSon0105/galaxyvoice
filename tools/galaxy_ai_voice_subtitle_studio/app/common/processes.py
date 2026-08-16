from __future__ import annotations

import os
import subprocess
import threading
from typing import Any


class ManagedProcessRegistry:
    def __init__(self) -> None:
        self._processes: set[subprocess.Popen[Any]] = set()
        self._lock = threading.Lock()
        self._stopping = False

    def reset(self) -> None:
        with self._lock:
            if not self._processes:
                self._stopping = False

    def add(self, process: subprocess.Popen[Any]) -> None:
        with self._lock:
            should_terminate = self._stopping
            if not should_terminate:
                self._processes.add(process)
        if should_terminate:
            terminate_process_tree(process)

    def discard(self, process: subprocess.Popen[Any]) -> None:
        with self._lock:
            self._processes.discard(process)

    def terminate_all(self) -> None:
        with self._lock:
            self._stopping = True
            processes = list(self._processes)
        for process in processes:
            terminate_process_tree(process)

    def ensure_running(self) -> None:
        with self._lock:
            stopping = self._stopping
        if stopping:
            raise RuntimeError("Media processing was cancelled because the app is closing.")

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "pid": process.pid,
                    "alive": process.poll() is None,
                }
                for process in self._processes
            ]


def terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            process.terminate()
    except OSError:
        try:
            process.terminate()
        except OSError:
            pass


managed_media_processes = ManagedProcessRegistry()
