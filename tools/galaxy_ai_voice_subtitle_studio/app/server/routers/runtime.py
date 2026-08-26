"""Thin HTTP surface for runtime discovery, preflight, and models."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...runtime.capabilities import PreflightRequest
from ...runtime.defaults import capability_registry, model_registry
from ...runtime.resources import shared_resource_scheduler
from ..tasks import task_registry

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


class PreflightBody(BaseModel):
    capability_id: str
    device: str = "auto"
    model_id: str = ""
    options: dict[str, str] = Field(default_factory=dict)


class InstallModelBody(BaseModel):
    capability_id: str
    model_id: str


@router.get("/capabilities")
def list_capabilities() -> list[dict[str, Any]]:
    return [asdict(item) for item in capability_registry.list_capabilities()]


@router.post("/preflight")
def preflight(body: PreflightBody) -> dict[str, Any]:
    return asdict(
        capability_registry.preflight(
            PreflightRequest(
                capability_id=body.capability_id,
                device=body.device,
                model_id=body.model_id,
                options=body.options,
            )
        )
    )


@router.get("/resources")
def resources() -> dict[str, object]:
    return shared_resource_scheduler.snapshot()


@router.get("/models")
def list_models(capability_id: str, refresh: bool = False) -> list[dict[str, Any]]:
    try:
        models = model_registry.list_models(capability_id, refresh)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return [asdict(model) for model in models]


@router.post("/models/install")
def install_model(body: InstallModelBody) -> dict[str, str]:
    record = task_registry.create(
        "model-install",
        capability_id=body.capability_id,
        resource_keys=("network",),
    )
    task_registry.submit(
        record,
        lambda context: model_registry.install(
            body.capability_id,
            body.model_id,
            context,
        ),
        asdict,
    )
    return {"task_id": record.task_id}
