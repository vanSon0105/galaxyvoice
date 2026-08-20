"""VoiceStudio iframe launcher endpoints."""
from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...common.config import load_app_config
from ...voicestudio.runtime import VoiceStudioRuntime, inspect_runtime
from ...voicestudio.service import VoiceStudioController

router = APIRouter(prefix="/api/voicestudio", tags=["voicestudio"])

_controller: VoiceStudioController | None = None
_controller_lock = threading.Lock()


def _get_controller() -> VoiceStudioController:
    global _controller
    with _controller_lock:
        if _controller is None:
            cfg = load_app_config()
            runtime = VoiceStudioRuntime.from_repository(environ=cfg.as_environ())
            _controller = VoiceStudioController(runtime)
        return _controller


class StatusResponse(BaseModel):
    installed: bool
    version: str
    message: str
    backend_online: bool
    update_required: bool
    missing_components: list[str]


class LaunchResponse(BaseModel):
    result: str  # "attached" | "local"
    url: str


class InstallRequest(BaseModel):
    pass


@router.get("/status")
def status() -> StatusResponse:
    """Check VoiceStudio installation and runtime status."""
    cfg = load_app_config()
    runtime = VoiceStudioRuntime.from_repository(environ=cfg.as_environ())
    s = inspect_runtime(runtime, probe_backend=True)
    return StatusResponse(
        installed=s.installed,
        version=s.version,
        message=s.message,
        backend_online=s.backend_online,
        update_required=s.update_required,
        missing_components=list(s.missing_components),
    )


@router.post("/launch")
def launch() -> LaunchResponse:
    """Launch VoiceStudio backend (or attach if already running)."""
    controller = _get_controller()
    cfg = load_app_config()
    runtime = VoiceStudioRuntime.from_repository(environ=cfg.as_environ())
    result = controller.launch()
    return LaunchResponse(result=result, url=runtime.backend_url)


@router.post("/install")
def install(request: InstallRequest) -> dict[str, Any]:
    """Start VoiceStudio installer as a background task."""
    from ..tasks import run_task, task_registry
    from ..event_bus import event_bus

    controller = _get_controller()

    if controller.installer_running():
        raise HTTPException(status_code=409, detail="Đang cài đặt VoiceStudio")

    # Check snapshot
    cfg = load_app_config()
    runtime = VoiceStudioRuntime.from_repository(environ=cfg.as_environ())
    if not runtime.snapshot_metadata_path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy snapshot VoiceStudio")

    record = task_registry.create("voicestudio-install")
    record.on_cancel = controller.stop_installer

    def _install_task() -> dict[str, Any]:
        process = controller.run_installer()
        # Monitor installer process
        while True:
            if process.poll() is not None:
                break
            # Emit log tail as progress
            tail = controller.installer_log_tail()
            event_bus.emit({"type": "progress", "task_id": record.task_id, "message": tail})
            time.sleep(1)
        controller.finish_installer(process)
        if process.returncode != 0:
            raise RuntimeError(f"Cài đặt thất bại (exit {process.returncode})")
        return {"success": True}

    def _on_done(task_record) -> None:
        if task_record.status == "done":
            event_bus.emit({"type": "event", "kind": "voicestudio_installed", "payload": {}})

    run_task(record, _install_task, _on_done)
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