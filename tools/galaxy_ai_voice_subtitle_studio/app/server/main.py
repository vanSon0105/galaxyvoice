"""FastAPI app for the Galaxy web shell.

Serves the API + WebSocket plus the built frontend (frontend/dist).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles

from .tasks import task_registry
from ..reliability.service import InsufficientDiskSpaceError

STUDIO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIST = STUDIO_ROOT / "frontend" / "dist"


class SpaStaticFiles(StaticFiles):
    """Serve React history routes without masking missing APIs or assets."""

    async def get_response(self, path: str, scope: dict[str, Any]):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if error.status_code != 404 or not self._is_spa_route(path):
                raise
            return await super().get_response("index.html", scope)

    @staticmethod
    def _is_spa_route(path: str) -> bool:
        normalized = path.replace("\\", "/").lstrip("/")
        first_segment = normalized.partition("/")[0].casefold()
        if first_segment in {"api", "assets", "ws"}:
            return False
        return not Path(normalized).suffix

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

    @app.exception_handler(InsufficientDiskSpaceError)
    async def insufficient_disk_space(
        _request: Request, error: InsufficientDiskSpaceError
    ) -> JSONResponse:
        return JSONResponse(status_code=507, content={"detail": str(error)})

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        record_health_ping()
        return {
            "status": "ok",
            "running_tasks": task_registry.running_count(),
        }

    from .files import router as files_router
    from .routers import audio_separation as audio_separation_router
    from .routers import audio_postproduction as audio_postproduction_router
    from .routers import batch as batch_router
    from .routers import omnivoice as omnivoice_router
    from .routers import omnivoice_workspaces as workspaces_router
    from .routers import project_graph as project_graph_router
    from .routers import reliability as reliability_router
    from .routers import runtime as runtime_router
    from .routers import settings as settings_router
    from .routers import studio as studio_router
    from .routers import subtitle_removal as subtitle_removal_router
    from .routers import video_editor as video_editor_router
    from .routers import tasks as tasks_router
    from .routers import transcripts as transcripts_router
    from .routers import voice as voice_router
    from .routers import voice_library as voice_library_router
    from .routers import voicestudio as voicestudio_router
    from .ws import router as ws_router

    app.include_router(tasks_router.router)
    app.include_router(runtime_router.router)
    app.include_router(reliability_router.router)
    app.include_router(settings_router.router)
    app.include_router(batch_router.router)
    app.include_router(studio_router.router)
    app.include_router(audio_separation_router.router)
    app.include_router(audio_postproduction_router.router)
    app.include_router(subtitle_removal_router.router)
    app.include_router(video_editor_router.router)
    app.include_router(voice_router.router)
    app.include_router(transcripts_router.router)
    app.include_router(voice_library_router.router)
    app.include_router(omnivoice_router.router)
    app.include_router(workspaces_router.router)
    app.include_router(project_graph_router.router)
    app.include_router(voicestudio_router.router)
    app.include_router(files_router)
    app.include_router(ws_router)

    if (FRONTEND_DIST / "index.html").is_file():
        app.mount("/", SpaStaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

    # Note: the event bus loop is bound by the WS handler itself, so the app
    # runs with lifespan disabled (lifespan="off" in shell.py) — avoids the
    # noisy CancelledError tracebacks uvicorn emits on thread shutdown.

    return app


app = create_app()
