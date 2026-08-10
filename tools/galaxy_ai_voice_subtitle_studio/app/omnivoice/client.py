from __future__ import annotations

import os
import queue
import subprocess
import threading
import uuid
from collections import deque
from pathlib import Path
from typing import Callable

from ..common.paths import studio_root
from ..common.processes import managed_media_processes, terminate_process_tree
from .protocol import decode_message, encode_message, request_message
from .runtime import OmniVoiceRuntime, inspect_runtime


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[str], None]


class OmniVoiceWorkerClient:
    def __init__(
        self,
        runtime: OmniVoiceRuntime,
        worker_path: Path,
        *,
        log: LogCallback | None = None,
    ) -> None:
        self.runtime = runtime
        self.worker_path = Path(worker_path)
        self._default_log = log
        self._process: subprocess.Popen[str] | None = None
        self._request_lock = threading.Lock()
        self._stderr_lines: deque[str] = deque(maxlen=30)
        self._stderr_queue: queue.Queue[str] = queue.Queue()
        self._stderr_thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def request(
        self,
        command: str,
        payload: dict[str, object],
        *,
        on_progress: ProgressCallback | None = None,
        on_log: LogCallback | None = None,
    ) -> dict[str, object]:
        with self._request_lock:
            process = self._ensure_started()
            request_id = uuid.uuid4().hex
            message = request_message(request_id, command, payload)
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("OmniVoice worker pipes are unavailable.")
            try:
                process.stdin.write(encode_message(message))
                process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                self._discard_process()
                raise RuntimeError("Không thể gửi lệnh tới OmniVoice worker.") from error

            while True:
                self._drain_stderr(on_log)
                raw = process.stdout.readline()
                if not raw:
                    details = "\n".join(self._stderr_lines)
                    self._discard_process()
                    suffix = f"\n{details}" if details else ""
                    raise RuntimeError(f"OmniVoice worker đã dừng ngoài ý muốn.{suffix}")
                response = decode_message(raw)
                if response.get("request_id") != request_id:
                    continue
                response_type = response.get("type")
                response_payload = response.get("payload")
                if response_type == "progress":
                    message_text = str(
                        response_payload.get("message", "Đang xử lý...")
                        if isinstance(response_payload, dict)
                        else response_payload
                    )
                    if on_progress:
                        on_progress(message_text)
                    continue
                if response_type == "error":
                    message_text = str(
                        response_payload.get("message", "OmniVoice worker failed.")
                        if isinstance(response_payload, dict)
                        else response_payload
                    )
                    raise RuntimeError(message_text)
                if response_type != "result" or not isinstance(response_payload, dict):
                    raise RuntimeError(f"Phản hồi OmniVoice không hợp lệ: {response_type}")
                self._drain_stderr(on_log)
                return response_payload

    def stop(self) -> None:
        self._terminate_process()

    def close(self) -> None:
        self._terminate_process()

    def _ensure_started(self) -> subprocess.Popen[str]:
        if self.is_running:
            assert self._process is not None
            return self._process
        status = inspect_runtime(self.runtime)
        if not status.installed:
            raise RuntimeError(status.message)
        if not self.worker_path.is_file():
            raise RuntimeError(f"Không tìm thấy OmniVoice worker: {self.worker_path}")
        managed_media_processes.ensure_running()
        self.runtime.ensure_directories()
        self._stderr_lines.clear()
        while True:
            try:
                self._stderr_queue.get_nowait()
            except queue.Empty:
                break
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["HF_HOME"] = str(self.runtime.cache_dir / "huggingface")
        environment["HF_HUB_CACHE"] = str(self.runtime.cache_dir / "huggingface" / "hub")
        bundled_bin = studio_root() / "bin"
        if bundled_bin.is_dir():
            environment["PATH"] = os.pathsep.join(
                (str(bundled_bin), environment.get("PATH", ""))
            )
        process = subprocess.Popen(
            [str(self.runtime.python_path), "-u", str(self.worker_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(self.worker_path.parent),
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        managed_media_processes.add(process)
        self._process = process
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            args=(process,),
            daemon=True,
            name="omnivoice-stderr",
        )
        self._stderr_thread.start()
        return process

    def _read_stderr(self, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            message = line.rstrip()
            if message:
                self._stderr_lines.append(message)
                self._stderr_queue.put(message)

    def _drain_stderr(self, callback: LogCallback | None) -> None:
        target = callback or self._default_log
        while True:
            try:
                message = self._stderr_queue.get_nowait()
            except queue.Empty:
                break
            if target:
                target(message)

    def _terminate_process(self) -> None:
        process = self._process
        stderr_thread = self._stderr_thread
        self._process = None
        self._stderr_thread = None
        if process is None:
            return
        terminate_process_tree(process)
        self._reap_process(process, stderr_thread)
        managed_media_processes.discard(process)

    def _discard_process(self) -> None:
        process = self._process
        stderr_thread = self._stderr_thread
        self._process = None
        self._stderr_thread = None
        if process is not None:
            terminate_process_tree(process)
            self._reap_process(process, stderr_thread)
            managed_media_processes.discard(process)

    @staticmethod
    def _reap_process(
        process: subprocess.Popen[str],
        stderr_thread: threading.Thread | None,
    ) -> None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if stderr_thread is not None and stderr_thread is not threading.current_thread():
            stderr_thread.join(timeout=1)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
