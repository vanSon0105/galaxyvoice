from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from ..common.cache import read_json, write_json_atomic
from .models import AssetReference, ProjectGraphNode, ProjectHandoff


class ProjectGraphRepository:
    """Atomic metadata store; it never copies, moves, or deletes media files."""

    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        key = str(self.path.resolve())
        with self._locks_guard:
            self._lock = self._locks.setdefault(key, threading.RLock())

    def load(self) -> tuple[tuple[ProjectGraphNode, ...], tuple[ProjectHandoff, ...]]:
        with self._lock:
            payload = read_json(self.path)
        if not isinstance(payload, dict):
            return (), ()
        nodes = tuple(
            _read_node(item)
            for item in payload.get("nodes", ())
            if isinstance(item, Mapping)
        )
        handoffs = tuple(
            _read_handoff(item)
            for item in payload.get("handoffs", ())
            if isinstance(item, Mapping)
        )
        return nodes, handoffs

    def save(
        self,
        nodes: tuple[ProjectGraphNode, ...],
        handoffs: tuple[ProjectHandoff, ...],
    ) -> None:
        with self._lock:
            write_json_atomic(
                self.path,
                {
                    "schema_version": 1,
                    "nodes": [asdict(item) for item in nodes],
                    "handoffs": [asdict(item) for item in handoffs],
                },
            )

    def mutate(self, callback):
        with self._lock:
            nodes, handoffs = self.load()
            updated_nodes, updated_handoffs, result = callback(nodes, handoffs)
            self.save(updated_nodes, updated_handoffs)
            return result


def _read_asset(payload: Mapping[str, Any]) -> AssetReference:
    metadata = payload.get("metadata")
    return AssetReference(
        asset_id=str(payload.get("asset_id") or ""),
        role=str(payload.get("role") or "asset"),
        path_hint=str(payload.get("path_hint") or ""),
        ownership=str(payload.get("ownership") or "linked"),
        fingerprint=str(payload.get("fingerprint") or ""),
        derived_from=tuple(str(item) for item in payload.get("derived_from", ())),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _read_node(payload: Mapping[str, Any]) -> ProjectGraphNode:
    metadata = payload.get("metadata")
    return ProjectGraphNode(
        node_id=str(payload.get("node_id") or ""),
        project_id=str(payload.get("project_id") or ""),
        workspace=str(payload.get("workspace") or ""),
        owner_id=str(payload.get("owner_id") or ""),
        label=str(payload.get("label") or ""),
        route=str(payload.get("route") or ""),
        revision=max(0, int(payload.get("revision") or 0)),
        assets=tuple(
            _read_asset(item)
            for item in payload.get("assets", ())
            if isinstance(item, Mapping)
        ),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
    )


def _read_handoff(payload: Mapping[str, Any]) -> ProjectHandoff:
    handoff_payload = payload.get("payload")
    return ProjectHandoff(
        handoff_id=str(payload.get("handoff_id") or ""),
        project_id=str(payload.get("project_id") or ""),
        source_node_id=str(payload.get("source_node_id") or ""),
        source_workspace=str(payload.get("source_workspace") or ""),
        source_revision=max(0, int(payload.get("source_revision") or 0)),
        source_route=str(payload.get("source_route") or ""),
        target_workspace=str(payload.get("target_workspace") or ""),
        target_route=str(payload.get("target_route") or ""),
        target_node_id=str(payload.get("target_node_id") or ""),
        status=str(payload.get("status") or "pending"),
        input_asset_ids=tuple(str(item) for item in payload.get("input_asset_ids", ())),
        output_asset_ids=tuple(str(item) for item in payload.get("output_asset_ids", ())),
        payload=dict(handoff_payload) if isinstance(handoff_payload, Mapping) else {},
        created_at=str(payload.get("created_at") or ""),
        opened_at=str(payload.get("opened_at") or ""),
        returned_at=str(payload.get("returned_at") or ""),
    )
