"""VoiceStudio iframe launcher endpoints."""
from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...common.errors import TaskCancelledError
from ...voicestudio.runtime import VoiceStudioRuntime, inspect_runtime
from ...voicestudio.service import VoiceStudioController

router = APIRouter(prefix="/api/voicestudio", tags=["voicestudio"])

_controller: VoiceStudioController | None = None
_controller_lock = threading.Lock()
_launch_lock = threading.Lock()
_install_task_id: str | None = None


def _get_controller() -> VoiceStudioController:
    global _controller
    with _controller_lock:
        if _controller is None:
            _controller = VoiceStudioController(VoiceStudioRuntime.from_repository())
        return _controller


def shutdown_voicestudio() -> None:
    """Stop processes owned by the shared web controller."""
    global _controller, _install_task_id
    with _controller_lock:
        controller = _controller
        _controller = None
        _install_task_id = None
    if controller is not None:
        controller.stop_all()


class StatusResponse(BaseModel):
    installed: bool
    version: str
    message: str
    backend_online: bool
    update_required: bool
    missing_components: list[str]
    backend_url: str


class LaunchResponse(BaseModel):
    result: str  # "attached" | "local"
    url: str


class InstallRequest(BaseModel):
    pass


@router.get("/status")
def status() -> StatusResponse:
    """Check VoiceStudio installation and runtime status."""
    controller = _get_controller()
    runtime = controller.runtime
    s = inspect_runtime(runtime, probe_backend=False)
    return StatusResponse(
        installed=s.installed,
        version=s.version,
        message=s.message,
        backend_online=controller.is_running(),
        update_required=s.update_required,
        missing_components=list(s.missing_components),
        backend_url=runtime.backend_url,
    )


@router.post("/launch")
def launch() -> LaunchResponse:
    """Launch VoiceStudio backend (or attach if already running)."""
    controller = _get_controller()
    with _launch_lock:
        result = controller.launch()
        if not controller.wait_until_ready():
            detail = controller.backend_log_tail(max_chars=1800)
            if result == "local":
                controller.stop()
            suffix = f"\n\nLog cuối:\n{detail}" if detail else ""
            raise HTTPException(
                status_code=503,
                detail=f"VoiceStudio không sẵn sàng sau khi khởi động.{suffix}",
            )
        controller.disable_upstream_analytics()
        return LaunchResponse(result=result, url=controller.runtime.backend_url)


@router.post("/install")
def install(request: InstallRequest) -> dict[str, Any]:
    """Start VoiceStudio installer as a background task."""
    from ..tasks import run_task, task_registry
    from ..event_bus import event_bus

    global _install_task_id
    controller = _get_controller()

    runtime = controller.runtime
    if not runtime.snapshot_metadata_path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy snapshot VoiceStudio")

    with _controller_lock:
        if _install_task_id is not None or controller.installer_running():
            raise HTTPException(status_code=409, detail="Đang cài đặt VoiceStudio")
        record = task_registry.create("voicestudio-install")
        _install_task_id = record.task_id
    record.on_cancel = controller.stop_installer
    event_bus.emit({"type": "task", "task_id": record.task_id, "status": "running"})

    def _install_task() -> dict[str, Any]:
        global _install_task_id
        process = None
        try:
            process = controller.run_installer()
            last_tail = ""
            while process.poll() is None:
                if record.stop_event.is_set():
                    raise TaskCancelledError("Đã dừng cài đặt VoiceStudio")
                tail = controller.installer_log_tail()
                if tail and tail != last_tail:
                    task_registry.report(record.task_id, tail)
                    last_tail = tail
                time.sleep(1)
            if record.stop_event.is_set():
                raise TaskCancelledError("Đã dừng cài đặt VoiceStudio")
            if process.returncode != 0:
                raise RuntimeError(f"Cài đặt thất bại (exit {process.returncode})")
            event_bus.emit({"type": "event", "kind": "voicestudio_installed", "payload": {}})
            return {"success": True}
        finally:
            if process is not None:
                controller.finish_installer(process)
            with _controller_lock:
                if _install_task_id == record.task_id:
                    _install_task_id = None

    run_task(record, _install_task, lambda result: result)
    return {"task_id": record.task_id}


@router.post("/stop")
def stop() -> dict[str, bool]:
    """Stop VoiceStudio backend."""
    controller = _get_controller()
    controller.stop_all()
    return {"success": True}


@router.get("/installer/log")
def installer_log() -> dict[str, str]:
    """Get installer log tail."""
    controller = _get_controller()
    return {"log": controller.installer_log_tail()}


@router.get("/backend/log")
def backend_log() -> dict[str, str]:
    """Get backend log tail."""
    controller = _get_controller()
    return {"log": controller.backend_log_tail()}
