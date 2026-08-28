from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...project_graph.models import AssetReference, HandoffRequest, NodeRequest
from ...project_graph.runtime import project_graph_service
from ...project_graph.service import ProjectGraphService, workspace_catalog


router = APIRouter(prefix="/api/project-graph", tags=["project-graph"])


class AssetBody(BaseModel):
    asset_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    path_hint: str = ""
    ownership: str = "linked"
    fingerprint: str = ""
    derived_from: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def contract(self) -> AssetReference:
        return AssetReference(
            asset_id=self.asset_id,
            role=self.role,
            path_hint=self.path_hint,
            ownership=self.ownership,
            fingerprint=self.fingerprint,
            derived_from=tuple(self.derived_from),
            metadata=self.metadata,
        )


class NodeBody(BaseModel):
    project_id: str = Field(min_length=1)
    workspace: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    label: str = ""
    revision: int = Field(0, ge=0)
    assets: list[AssetBody] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def contract(self) -> NodeRequest:
        return NodeRequest(
            project_id=self.project_id,
            workspace=self.workspace,
            owner_id=self.owner_id,
            label=self.label,
            revision=self.revision,
            assets=tuple(item.contract() for item in self.assets),
            metadata=self.metadata,
        )


class HandoffBody(BaseModel):
    project_id: str = Field(min_length=1)
    source_node_id: str = Field(min_length=1)
    target_workspace: str = Field(min_length=1)
    input_asset_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    handoff_id: str = ""


class ReturnBody(BaseModel):
    target_node: NodeBody | None = None
    target_node_id: str = ""
    output_asset_ids: list[str] = Field(default_factory=list)


def _service(request: Request) -> ProjectGraphService:
    configured = getattr(request.app.state, "settings_path", None)
    return project_graph_service(Path(configured) if configured is not None else None)


@router.get("/workspaces")
def list_workspaces() -> list[dict[str, Any]]:
    return [
        {
            "id": item.workspace_id,
            "label": item.label,
            "route": item.route,
            "targets": list(item.targets),
        }
        for item in workspace_catalog()
    ]


@router.get("/projects/{project_id}")
def get_project_graph(project_id: str, request: Request) -> dict[str, Any]:
    try:
        return asdict(_service(request).get_graph(project_id))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/nodes")
def upsert_node(body: NodeBody, request: Request) -> dict[str, Any]:
    try:
        return asdict(_service(request).upsert_node(body.contract()))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/handoffs")
def create_handoff(body: HandoffBody, request: Request) -> dict[str, Any]:
    try:
        return asdict(
            _service(request).create_handoff(
                HandoffRequest(
                    project_id=body.project_id,
                    source_node_id=body.source_node_id,
                    target_workspace=body.target_workspace,
                    input_asset_ids=tuple(body.input_asset_ids),
                    payload=body.payload,
                    handoff_id=body.handoff_id,
                )
            )
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Không tìm thấy node nguồn.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/handoffs/{handoff_id}")
def get_handoff(handoff_id: str, request: Request) -> dict[str, Any]:
    try:
        return asdict(_service(request).get_handoff(handoff_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Không tìm thấy handoff.") from error


@router.post("/handoffs/{handoff_id}/open")
def open_handoff(handoff_id: str, request: Request) -> dict[str, Any]:
    try:
        return asdict(_service(request).open_handoff(handoff_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Không tìm thấy handoff.") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/handoffs/{handoff_id}/return")
def return_handoff(handoff_id: str, body: ReturnBody, request: Request) -> dict[str, Any]:
    try:
        return asdict(
            _service(request).return_handoff(
                handoff_id,
                target_node=body.target_node.contract() if body.target_node else None,
                target_node_id=body.target_node_id,
                output_asset_ids=tuple(body.output_asset_ids),
            )
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Không tìm thấy handoff.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
