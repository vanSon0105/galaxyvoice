from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .models import (
    AssetReference,
    HandoffRequest,
    NodeRequest,
    ProjectGraph,
    ProjectGraphNode,
    ProjectHandoff,
    WorkspaceSpec,
)
from .repository import ProjectGraphRepository


_WORKSPACES = (
    WorkspaceSpec("studio", "Studio", "/voice", ("batch", "editor", "separation", "transcripts", "longform", "dubbing")),
    WorkspaceSpec("batch", "Batch", "/voice/batch", ("studio", "editor", "separation", "longform")),
    WorkspaceSpec("library", "Thư viện giọng", "/voice/library", ("studio", "batch", "longform", "dubbing")),
    WorkspaceSpec("transcripts", "Transcripts", "/voice/transcripts", ("dubbing", "longform", "editor")),
    WorkspaceSpec("longform", "Truyện & Sách nói", "/voice/longform", ("studio", "batch", "editor", "separation", "transcripts", "dubbing")),
    WorkspaceSpec("dubbing", "Dubbing", "/voice/dubbing", ("editor", "separation", "transcripts", "longform", "subtitle_removal")),
    WorkspaceSpec("editor", "Dựng video", "/editor", ("transcripts", "dubbing", "separation", "subtitle_removal")),
    WorkspaceSpec("separation", "Tách âm thanh", "/separation", ("editor", "dubbing", "transcripts")),
    WorkspaceSpec("subtitle_removal", "Xóa phụ đề", "/removal", ("editor", "transcripts", "dubbing")),
)
_WORKSPACE_BY_ID = {item.workspace_id: item for item in _WORKSPACES}
_SECRET_MARKERS = ("api_key", "apikey", "token", "secret", "authorization")


def workspace_catalog() -> tuple[WorkspaceSpec, ...]:
    return _WORKSPACES


class ProjectGraphService:
    def __init__(self, path: Path) -> None:
        self.repository = ProjectGraphRepository(path)

    def get_graph(self, project_id: str) -> ProjectGraph:
        normalized = _required(project_id, "Project ID")
        nodes, handoffs = self.repository.load()
        selected_nodes = tuple(item for item in nodes if item.project_id == normalized)
        selected_handoffs = tuple(item for item in handoffs if item.project_id == normalized)
        timestamps = [item.updated_at for item in selected_nodes]
        timestamps.extend(item.returned_at or item.opened_at or item.created_at for item in selected_handoffs)
        return ProjectGraph(
            project_id=normalized,
            nodes=tuple(sorted(selected_nodes, key=lambda item: item.updated_at, reverse=True)),
            handoffs=tuple(sorted(selected_handoffs, key=lambda item: item.created_at, reverse=True)),
            updated_at=max(timestamps, default=""),
        )

    def get_handoff(self, handoff_id: str) -> ProjectHandoff:
        _nodes, handoffs = self.repository.load()
        item = next((entry for entry in handoffs if entry.handoff_id == handoff_id), None)
        if item is None:
            raise KeyError(handoff_id)
        return item

    def upsert_node(self, request: NodeRequest) -> ProjectGraphNode:
        project_id = _required(request.project_id, "Project ID")
        workspace = _workspace(request.workspace)
        owner_id = _required(request.owner_id, "Owner ID")
        node_id = f"{workspace.workspace_id}:{owner_id}"
        assets = _deduplicate_assets(request.assets)
        metadata = _sanitize(request.metadata)

        def apply(nodes, handoffs):
            existing = next((item for item in nodes if item.node_id == node_id), None)
            if existing is not None and existing.project_id != project_id:
                raise ValueError("Node đã thuộc một Active Project khác.")
            now = _now()
            node = ProjectGraphNode(
                node_id=node_id,
                project_id=project_id,
                workspace=workspace.workspace_id,
                owner_id=owner_id,
                label=request.label.strip() or workspace.label,
                route=workspace.route,
                revision=max(0, int(request.revision)),
                assets=assets,
                metadata=metadata,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            updated = tuple(node if item.node_id == node_id else item for item in nodes)
            if existing is None:
                updated = (*updated, node)
            return updated, handoffs, node

        return self.repository.mutate(apply)

    def create_handoff(self, request: HandoffRequest) -> ProjectHandoff:
        project_id = _required(request.project_id, "Project ID")
        target = _workspace(request.target_workspace)

        def apply(nodes, handoffs):
            source = next((item for item in nodes if item.node_id == request.source_node_id), None)
            if source is None:
                raise KeyError(request.source_node_id)
            if source.project_id != project_id:
                raise ValueError("Node nguồn không thuộc Active Project này.")
            source_spec = _workspace(source.workspace)
            if target.workspace_id not in source_spec.targets:
                raise ValueError(
                    f"Handoff {source_spec.label} → {target.label} không được hỗ trợ."
                )
            available_assets = {item.asset_id for item in source.assets}
            missing = set(request.input_asset_ids) - available_assets
            if missing:
                raise ValueError(f"Asset nguồn không thuộc node: {', '.join(sorted(missing))}")
            handoff_id = request.handoff_id.strip() or uuid4().hex
            if any(item.handoff_id == handoff_id for item in handoffs):
                raise ValueError("Handoff ID đã tồn tại.")
            handoff = ProjectHandoff(
                handoff_id=handoff_id,
                project_id=project_id,
                source_node_id=source.node_id,
                source_workspace=source.workspace,
                source_revision=source.revision,
                source_route=source.route,
                target_workspace=target.workspace_id,
                target_route=target.route,
                target_node_id="",
                status="pending",
                input_asset_ids=tuple(dict.fromkeys(request.input_asset_ids)),
                output_asset_ids=(),
                payload=_sanitize(request.payload),
                created_at=_now(),
                opened_at="",
                returned_at="",
            )
            return nodes, (*handoffs, handoff), handoff

        return self.repository.mutate(apply)

    def open_handoff(self, handoff_id: str) -> ProjectHandoff:
        def apply(nodes, handoffs):
            current = _find_handoff(handoffs, handoff_id)
            if current.status == "returned":
                raise ValueError("Handoff đã hoàn tất và có bản ghi quay lại nguồn.")
            replacement = current if current.status == "opened" else replace(
                current, status="opened", opened_at=_now()
            )
            return nodes, _replace_handoff(handoffs, replacement), replacement

        return self.repository.mutate(apply)

    def return_handoff(
        self,
        handoff_id: str,
        *,
        target_node: NodeRequest | None = None,
        target_node_id: str = "",
        output_asset_ids: tuple[str, ...] = (),
    ) -> ProjectHandoff:
        if target_node is not None and target_node_id.strip():
            raise ValueError("Chỉ được chọn một node đích khi hoàn tất handoff.")
        if target_node is not None:
            current = self.get_handoff(handoff_id)
            if target_node.project_id != current.project_id:
                raise ValueError("Node đích không thuộc Active Project của handoff.")
            if target_node.workspace != current.target_workspace:
                raise ValueError("Workspace node đích không khớp handoff.")
            saved_target = self.upsert_node(target_node)
        else:
            saved_target = None

        def apply(nodes, handoffs):
            current = _find_handoff(handoffs, handoff_id)
            if current.status == "returned":
                return nodes, handoffs, current
            resolved_target = saved_target
            if resolved_target is None and target_node_id.strip():
                resolved_target = next(
                    (item for item in nodes if item.node_id == target_node_id.strip()),
                    None,
                )
                if resolved_target is None:
                    raise ValueError("Node đích chưa có trong project graph.")
            if resolved_target is not None:
                if resolved_target.project_id != current.project_id:
                    raise ValueError("Node đích không thuộc Active Project của handoff.")
                if resolved_target.workspace != current.target_workspace:
                    raise ValueError("Workspace node đích không khớp handoff.")
                available = {asset.asset_id for asset in resolved_target.assets}
            else:
                available = {
                    asset.asset_id
                    for node in nodes
                    if node.project_id == current.project_id
                    for asset in node.assets
                }
            missing = set(output_asset_ids) - available
            if missing:
                raise ValueError(f"Asset đầu ra chưa có trong graph: {', '.join(sorted(missing))}")
            replacement = replace(
                current,
                target_node_id=(
                    resolved_target.node_id if resolved_target else current.target_node_id
                ),
                status="returned",
                output_asset_ids=tuple(dict.fromkeys(output_asset_ids)),
                opened_at=current.opened_at or _now(),
                returned_at=_now(),
            )
            return nodes, _replace_handoff(handoffs, replacement), replacement

        return self.repository.mutate(apply)


def _workspace(value: str) -> WorkspaceSpec:
    normalized = value.strip().casefold()
    spec = _WORKSPACE_BY_ID.get(normalized)
    if spec is None:
        raise ValueError(f"Workspace không hợp lệ: {value}")
    return spec


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} không được để trống.")
    return normalized


def _deduplicate_assets(assets: tuple[AssetReference, ...]) -> tuple[AssetReference, ...]:
    by_id: dict[str, AssetReference] = {}
    for asset in assets:
        if asset.asset_id in by_id:
            raise ValueError(f"Asset ID bị trùng trong node: {asset.asset_id}")
        by_id[asset.asset_id] = replace(asset, metadata=_sanitize(asset.metadata))
    return tuple(by_id.values())


def _find_handoff(
    handoffs: tuple[ProjectHandoff, ...], handoff_id: str
) -> ProjectHandoff:
    item = next((entry for entry in handoffs if entry.handoff_id == handoff_id), None)
    if item is None:
        raise KeyError(handoff_id)
    return item


def _replace_handoff(
    handoffs: tuple[ProjectHandoff, ...], replacement: ProjectHandoff
) -> tuple[ProjectHandoff, ...]:
    return tuple(
        replacement if item.handoff_id == replacement.handoff_id else item
        for item in handoffs
    )


def _sanitize(payload: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for raw_key, value in payload.items():
        key = str(raw_key)
        normalized = key.casefold()
        if any(marker in normalized for marker in _SECRET_MARKERS):
            continue
        if isinstance(value, Mapping):
            cleaned[key] = _sanitize(value)
        elif isinstance(value, (list, tuple)):
            cleaned[key] = [
                _sanitize(item) if isinstance(item, Mapping) else item
                for item in value
                if item is None or isinstance(item, (Mapping, str, int, float, bool))
            ]
        elif value is None or isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
    return cleaned


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
