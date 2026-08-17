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

from .tasks import task_registry

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

    from .files import router as files_router
    from .routers import omnivoice as omnivoice_router
    from .routers import settings as settings_router
    from .routers import tasks as tasks_router
    from .routers import voice as voice_router
    from .ws import router as ws_router

    app.include_router(tasks_router.router)
    app.include_router(settings_router.router)
    app.include_router(voice_router.router)
    app.include_router(omnivoice_router.router)
    app.include_router(files_router)
    app.include_router(ws_router)

    if (FRONTEND_DIST / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

    # Note: the event bus loop is bound by the WS handler itself, so the app
    # runs with lifespan disabled (lifespan="off" in shell.py) — avoids the
    # noisy CancelledError tracebacks uvicorn emits on thread shutdown.

    return app


app = create_app()
