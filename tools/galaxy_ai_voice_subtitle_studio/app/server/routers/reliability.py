"""Thin HTTP surface for system diagnostics and operation audits."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ...common.config import default_config_path, load_app_config
from ...common.diagnostics import default_log_path
from ...reliability.service import ReliabilityService, read_diagnostic_log
from ...runtime.capabilities import PreflightRequest
from ...runtime.defaults import capability_registry

router = APIRouter(prefix="/api/reliability", tags=["reliability"])
service = ReliabilityService(capability_registry)


class AuditBody(BaseModel):
    capability_id: str
    device: str = "auto"
    model_id: str = ""
    options: dict[str, str] = Field(default_factory=dict)
    output_path: str = ""
    required_disk_bytes: int = Field(default=0, ge=0)


def _settings_path(request: Request) -> Path:
    configured = getattr(request.app.state, "settings_path", None)
    return Path(configured) if configured is not None else default_config_path()


@router.get("/report")
def system_report(request: Request) -> dict[str, Any]:
    settings_path = _settings_path(request)
    config = load_app_config(settings_path)
    paths = tuple(
        Path(value)
        for value in (
            config.output_dir,
            config.audio_output_dir,
            config.editor_output_dir,
            config.omnivoice_output_dir,
        )
        if value
    )
    if not paths:
        paths = (settings_path.parent,)
    return asdict(service.system_report(paths))


@router.post("/audit")
def operation_audit(body: AuditBody) -> dict[str, Any]:
    try:
        capability_registry.get(body.capability_id)
        result = service.audit(
            PreflightRequest(
                capability_id=body.capability_id,
                device=body.device,
                model_id=body.model_id,
                options=body.options,
            ),
            output_path=body.output_path,
            required_disk_bytes=body.required_disk_bytes,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return asdict(result)


@router.get("/logs")
def diagnostic_logs(limit: int = Query(default=200, ge=1, le=1_000)) -> dict[str, Any]:
    return {"path": str(default_log_path()), "lines": read_diagnostic_log(limit=limit)}
