from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


ASSET_OWNERSHIP = frozenset({"managed", "linked", "generated"})
HANDOFF_STATUSES = frozenset({"pending", "opened", "returned"})


@dataclass(frozen=True)
class WorkspaceSpec:
    workspace_id: str
    label: str
    route: str
    targets: tuple[str, ...]


@dataclass(frozen=True)
class AssetReference:
    asset_id: str
    role: str
    path_hint: str = ""
    ownership: str = "linked"
    fingerprint: str = ""
    derived_from: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.asset_id.strip() or not self.role.strip():
            raise ValueError("Asset ID và vai trò không được để trống.")
        if self.ownership not in ASSET_OWNERSHIP:
            raise ValueError(f"Quyền sở hữu asset không hợp lệ: {self.ownership}")


@dataclass(frozen=True)
class NodeRequest:
    project_id: str
    workspace: str
    owner_id: str
    label: str
    revision: int = 0
    assets: tuple[AssetReference, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectGraphNode:
    node_id: str
    project_id: str
    workspace: str
    owner_id: str
    label: str
    route: str
    revision: int
    assets: tuple[AssetReference, ...]
    metadata: Mapping[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class HandoffRequest:
    project_id: str
    source_node_id: str
    target_workspace: str
    input_asset_ids: tuple[str, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)
    handoff_id: str = ""


@dataclass(frozen=True)
class ProjectHandoff:
    handoff_id: str
    project_id: str
    source_node_id: str
    source_workspace: str
    source_revision: int
    source_route: str
    target_workspace: str
    target_route: str
    target_node_id: str
    status: str
    input_asset_ids: tuple[str, ...]
    output_asset_ids: tuple[str, ...]
    payload: Mapping[str, Any]
    created_at: str
    opened_at: str
    returned_at: str


@dataclass(frozen=True)
class ProjectGraph:
    project_id: str
    nodes: tuple[ProjectGraphNode, ...]
    handoffs: tuple[ProjectHandoff, ...]
    updated_at: str
