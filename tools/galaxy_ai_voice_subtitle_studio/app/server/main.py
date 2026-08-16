"""FastAPI app for the Galaxy web shell.

Serves the API + WebSocket plus the built frontend (frontend/dist).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .event_bus import event_bus
from .tasks import CANCELLED, DONE, FAILED, task_registry

STUDIO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIST = STUDIO_ROOT / "frontend" / "dist"

# Watchdog bookkeeping: the UI pings /api/health every 5 s; the shell exits
# if no ping arrives for too long (window crashed without a clean close).
_health_lock = threading.Lock()
_last_health_ping = time.time()


def record_health_ping() -> None:
    global _last_health_ping
    with _health_lock:
        _last_health_ping = time.time()


def health_ping_age() -> float:
    with _health_lock:
        return time.time() - _last_health_ping





def _run_spike_task(task_id: str) -> None:
    record = task_registry.get(task_id)
    if record is None:
        return
    try:
        for index in range(1, 6):
            if record.stop_event.is_set():
                task_registry.finish(task_id, status=CANCELLED)
                event_bus.emit({"type": "task", "task_id": task_id, "status": CANCELLED})
                return
            event_bus.emit(
                {"type": "progress", "task_id": task_id, "message": f"bước {index}/5"}
            )
            record.stop_event.wait(1.0)
        task_registry.finish(task_id, status=DONE, result={"steps": 5})
        event_bus.emit({"type": "task", "task_id": task_id, "status": DONE, "result": {"steps": 5}})
    except Exception as error:  # pragma: no cover - safety net
        task_registry.finish(task_id, status=FAILED, error=str(error))
        event_bus.emit({"type": "task", "task_id": task_id, "status": FAILED, "error": str(error)})


def create_app(config_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Galaxy AI Voice & Subtitle Studio")
    app.state.settings_path = config_path

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        record_health_ping()
        return {
            "status": "ok",
            "running_tasks": task_registry.running_count(),
        }

    @app.post("/api/spike/task")
    def spike_task() -> dict[str, Any]:
        record = task_registry.create("spike")
        event_bus.emit({"type": "task", "task_id": record.task_id, "status": "running"})
        threading.Thread(
            target=_run_spike_task,
            args=(record.task_id,),
            name=f"spike-{record.task_id}",
            daemon=True,
        ).start()
        return {"task_id": record.task_id}

    from .routers import settings as settings_router
    from .routers import tasks as tasks_router
    from .ws import router as ws_router

    app.include_router(tasks_router.router)
    app.include_router(settings_router.router)
    app.include_router(ws_router)

    if (FRONTEND_DIST / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

    # Note: the event bus loop is bound by the WS handler itself, so the app
    # runs with lifespan disabled (lifespan="off" in shell.py) — avoids the
    # noisy CancelledError tracebacks uvicorn emits on thread shutdown.

    return app


app = create_app()
