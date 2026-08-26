"""pywebview window + in-process uvicorn server lifecycle.

The Windows message pump (pywebview) must own the main thread, so uvicorn
runs in a daemon thread. Shutdown is a single path: stop uvicorn, kill the
managed media process trees, then hard-exit — no orphans (the app has a
history of leaked uvicorn/ffmpeg processes on this machine).
"""
from __future__ import annotations

import logging
import os
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from ..common.processes import managed_media_processes
from ..omnivoice.worker_pool import shutdown_shared_worker_client
from ..runtime.jobs import JobStore, default_job_store_path
from .main import create_app, health_ping_age
from .routers.voicestudio import shutdown_voicestudio
from .tasks import task_registry

LOGGER = logging.getLogger("galaxy.web.shell")

DEFAULT_PORT = 3902
PORT_RETRY_LIMIT = 3912
HEALTH_TIMEOUT_SECONDS = 15.0
HEALTH_POLL_SECONDS = 0.1
WATCHDOG_INTERVAL_SECONDS = 5.0
WATCHDOG_STALE_SECONDS = 60.0


class _NoSignalServer(uvicorn.Server):
    """uvicorn Server that never touches OS signal handlers (thread context)."""

    def install_signal_handlers(self) -> None:
        pass


class GalaxyWebServer:
    def __init__(
        self,
        *,
        port: int = DEFAULT_PORT,
        dev_url: str | None = None,
        debug: bool = False,
    ) -> None:
        self.port = port
        self.dev_url = dev_url
        self.debug = debug
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return self.dev_url or f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        """Start uvicorn in a daemon thread, retrying the next port on bind failure."""
        task_registry.configure_store(JobStore(default_job_store_path()))
        app = create_app()
        port = self.port
        while port <= PORT_RETRY_LIMIT:
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="info" if self.debug else "warning",
                timeout_graceful_shutdown=5,
                lifespan="off",
            )
            server = _NoSignalServer(config)
            thread = threading.Thread(
                target=server.run,
                name="galaxy-web-server",
                daemon=True,
            )
            thread.start()
            deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if server.started:
                    self._server = server
                    self._thread = thread
                    self.port = port
                    return
                if not thread.is_alive():
                    break  # exited immediately (e.g. port in use) -> next port
                time.sleep(HEALTH_POLL_SECONDS)
            port += 1
        raise RuntimeError(
            f"Không khởi động được web server trên cổng {self.port}–{PORT_RETRY_LIMIT}"
        )

    def wait_until_ready(self, timeout: float = HEALTH_TIMEOUT_SECONDS) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/api/health",
                    timeout=1.0,
                ) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(HEALTH_POLL_SECONDS)
        raise RuntimeError("Web server không sẵn sàng sau khi khởi động")

    def shutdown(self) -> None:
        """Cancel work, stop child processes and then stop uvicorn. Idempotent."""
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.should_exit = True
        task_registry.cancel_all()
        try:
            shutdown_voicestudio()
        except Exception:
            LOGGER.exception("Could not stop VoiceStudio during shutdown")
        try:
            shutdown_shared_worker_client()
        except Exception:
            LOGGER.exception("Could not stop OmniVoice worker during shutdown")
        managed_media_processes.terminate_all()
        lingering_tasks = task_registry.wait_for_running(timeout=5)
        if lingering_tasks:
            LOGGER.warning("Tasks still running during shutdown: %s", ", ".join(lingering_tasks))
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive() and server is not None:
                server.force_exit = True
                thread.join(timeout=5)


def _watchdog(server: GalaxyWebServer) -> None:
    """Exit the process if the window died without pinging health (crash)."""
    # Grace period while the window/web page is still loading.
    grace_until = time.monotonic() + WATCHDOG_STALE_SECONDS
    while True:
        time.sleep(WATCHDOG_INTERVAL_SECONDS)
        if time.monotonic() < grace_until:
            continue
        if health_ping_age() > WATCHDOG_STALE_SECONDS:
            LOGGER.warning("Web shell watchdog: no health pings; shutting down")
            server.shutdown()
            os._exit(0)


def run_web_app(
    *,
    port: int = DEFAULT_PORT,
    dev_url: str | None = None,
    serve_only: bool = False,
    debug: bool = False,
) -> int:
    server = GalaxyWebServer(port=port, dev_url=dev_url, debug=debug)
    server.start()
    server.wait_until_ready()

    if serve_only:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
        return 0

    import webview  # lazy: command-line tasks do not need pywebview installed

    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except KeyError:  # pragma: no cover - settings key varies across versions
        pass

    class GalaxyJsApi:
        """Native dialog bridge for the web UI.

        pywebview 6 no longer injects a built-in create_file_dialog into the
        JS bridge, so the native dialogs are exposed explicitly via js_api.
        """

        _VIDEO_FILE_TYPES = (
            "Video files (*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v)",
            "All files (*.*)",
        )
        _SRT_FILE_TYPES = ("Subtitle files (*.srt)", "All files (*.*)")
        _BOOK_FILE_TYPES = (
            "Sách và kịch bản (*.txt;*.md;*.epub;*.pdf)",
            "All files (*.*)",
        )

        def choose_video_file(self) -> tuple[str] | None:
            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=self._VIDEO_FILE_TYPES,
            )
            return result

        def choose_srt_file(self) -> tuple[str] | None:
            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=self._SRT_FILE_TYPES,
            )
            return result

        def choose_audio_file(self) -> tuple[str] | None:
            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=(
                    "Audio files (*.wav;*.mp3;*.flac;*.m4a;*.ogg)",
                    "All files (*.*)",
                ),
            )
            return result

        def choose_media_file(self) -> tuple[str] | None:
            return window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=(
                    "Media files (*.wav;*.mp3;*.flac;*.m4a;*.ogg;*.aac;*.wma;*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v)",
                    "All files (*.*)",
                ),
            )

        def choose_book_file(self) -> tuple[str] | None:
            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=self._BOOK_FILE_TYPES,
            )
            return result

        def choose_folder(self) -> tuple[str] | None:
            result = window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
            return result

    window = webview.create_window(
        "Galaxy AI Voice & Subtitle Studio",
        server.url,
        width=1280,
        height=800,
        min_size=(1080, 680),
        background_color="#111315",
        js_api=GalaxyJsApi(),
    )
    closed = threading.Event()

    def _on_closed() -> None:
        closed.set()

    window.events.closed += _on_closed

    threading.Thread(
        target=_watchdog,
        args=(server,),
        name="galaxy-web-watchdog",
        daemon=True,
    ).start()

    try:
        webview.start(debug=debug)
    finally:
        server.shutdown()

    # Backstop: pywebview start() returned; never fall through to a second UI.
    os._exit(0 if closed.is_set() else 1)
