"""Repository-backed behavioral probes for native parity checks."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ..common.errors import TaskCancelledError
from ..omnivoice.workspaces.longform_project import LongformProject, LongformProjectRepository
from ..project_graph.models import AssetReference, HandoffRequest, NodeRequest
from ..project_graph.repository import ProjectGraphRepository
from ..project_graph.service import ProjectGraphService, workspace_catalog
from .evidence import ArtifactCheckEvidence, RepositoryCheckEvidence
from .security import fingerprint_source, resolve_approved_path


_PROJECT_CHECKS = frozenset(
    {
        "project_reopen",
        "moved_directory_portability",
        "missing_media_relink",
        "handoff_return",
    }
)
_MAX_REPOSITORY_FIXTURE_BYTES = 8 * 1024 * 1024
_MAX_RELINK_TARGET_BYTES = 128 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024


def run_repository_check(
    case_id: str,
    check_id: str,
    request: ArtifactCheckEvidence,
    assets: Mapping[str, Path],
    *,
    approved_roots: Sequence[Path],
    check_cancelled: Callable[[], None],
) -> RepositoryCheckEvidence:
    """Execute a check through Galaxy repositories instead of trusting proof JSON."""
    try:
        check_cancelled()
        source = assets.get(request.role)
        if source is None:
            return _blocked(check_id, "Behavior fixture is unavailable")
        source = resolve_approved_path(source, approved_roots)
        fingerprint = fingerprint_source(source, check_cancelled=check_cancelled)
        if fingerprint.kind != "file" or fingerprint.sha256 != request.sha256:
            return _failed(check_id, "Behavior fixture checksum differs")
        if check_id in _PROJECT_CHECKS:
            return _run_project_graph_check(
                check_id,
                source,
                assets,
                approved_roots=approved_roots,
                check_cancelled=check_cancelled,
            )
        if check_id == "checkpoint_resume":
            return _run_longform_checkpoint_check(
                case_id,
                check_id,
                source,
                check_cancelled=check_cancelled,
            )
        return _blocked(check_id, "No Galaxy repository probe is registered")
    except TaskCancelledError:
        raise
    except Exception as error:
        return _failed(check_id, f"Galaxy repository probe failed: {type(error).__name__}")


def _run_project_graph_check(
    check_id: str,
    source: Path,
    assets: Mapping[str, Path],
    *,
    approved_roots: Sequence[Path],
    check_cancelled: Callable[[], None],
) -> RepositoryCheckEvidence:
    with tempfile.TemporaryDirectory(prefix="galaxy-parity-project-") as temporary:
        root = Path(temporary)
        first_root = root / "selected"
        first_root.mkdir()
        graph_path = first_root / "project_graph.json"
        _copy_file(
            source,
            graph_path,
            max_bytes=_MAX_REPOSITORY_FIXTURE_BYTES,
            check_cancelled=check_cancelled,
        )
        repository = ProjectGraphRepository(graph_path)
        before = repository.load()
        if not before[0]:
            return _failed(check_id, "Project graph fixture contains no nodes")
        check_cancelled()

        if check_id == "project_reopen":
            repository.save(*before)
            reopened = ProjectGraphRepository(graph_path).load()
            if _graph_payload(before) != _graph_payload(reopened):
                return _failed(check_id, "Project changed after repository reopen")
            return _passed(
                check_id,
                "Project reopened through ProjectGraphRepository",
                repository="project_graph",
                node_count=len(reopened[0]),
                handoff_count=len(reopened[1]),
            )

        if check_id == "moved_directory_portability":
            repository.save(*before)
            moved_root = root / "moved"
            shutil.move(str(first_root), moved_root)
            check_cancelled()
            reopened = ProjectGraphRepository(moved_root / graph_path.name).load()
            if _graph_payload(before) != _graph_payload(reopened):
                return _failed(check_id, "Project changed after its directory moved")
            return _passed(
                check_id,
                "Moved project reopened through ProjectGraphRepository",
                repository="project_graph",
                node_count=len(reopened[0]),
            )

        service = ProjectGraphService(graph_path)
        if check_id == "missing_media_relink":
            return _run_relink_check(
                check_id,
                service,
                source,
                assets,
                approved_roots=approved_roots,
                check_cancelled=check_cancelled,
            )
        return _run_handoff_check(check_id, service, check_cancelled=check_cancelled)


def _run_relink_check(
    check_id: str,
    service: ProjectGraphService,
    source: Path,
    assets: Mapping[str, Path],
    *,
    approved_roots: Sequence[Path],
    check_cancelled: Callable[[], None],
) -> RepositoryCheckEvidence:
    nodes, _handoffs = service.repository.load()
    selected = next(
        (
            (node, asset, str(asset.metadata.get("relink_role") or "").strip())
            for node in nodes
            for asset in node.assets
            if str(asset.metadata.get("relink_role") or "").strip()
        ),
        None,
    )
    if selected is None:
        return _failed(check_id, "Project graph has no relinkable asset declaration")
    node, asset, target_role = selected
    target = assets.get(target_role)
    if target is None:
        return _blocked(check_id, "Declared relink target is unavailable")
    target = resolve_approved_path(target, approved_roots)
    target_fingerprint = fingerprint_source(target, check_cancelled=check_cancelled)
    if target_fingerprint.kind != "file" or asset.fingerprint != target_fingerprint.sha256:
        return _failed(check_id, "Relink target fingerprint differs")
    original_hint = Path(asset.path_hint)
    original = original_hint if original_hint.is_absolute() else source.parent / original_hint
    if original.exists():
        return _failed(check_id, "Relink fixture is not missing before repair")

    managed_dir = service.repository.path.parent / "media"
    managed_dir.mkdir()
    managed_target = managed_dir / target.name
    _copy_file(
        target,
        managed_target,
        max_bytes=_MAX_RELINK_TARGET_BYTES,
        check_cancelled=check_cancelled,
    )
    replacement = replace(
        asset,
        path_hint=managed_target.relative_to(service.repository.path.parent).as_posix(),
    )
    service.upsert_node(
        NodeRequest(
            project_id=node.project_id,
            workspace=node.workspace,
            owner_id=node.owner_id,
            label=node.label,
            revision=node.revision + 1,
            assets=tuple(
                replacement if item.asset_id == asset.asset_id else item
                for item in node.assets
            ),
            metadata=node.metadata,
        )
    )
    check_cancelled()
    reopened = ProjectGraphService(service.repository.path).get_graph(node.project_id)
    repaired = next(
        item
        for current in reopened.nodes
        for item in current.assets
        if item.asset_id == asset.asset_id
    )
    repaired_path = service.repository.path.parent / repaired.path_hint
    repaired_fingerprint = fingerprint_source(repaired_path, check_cancelled=check_cancelled)
    if repaired_fingerprint.sha256 != asset.fingerprint:
        return _failed(check_id, "Relinked media changed after repository reopen")
    return _passed(
        check_id,
        "Missing media was relinked and reopened through ProjectGraphService",
        repository="project_graph",
        asset_id=asset.asset_id,
        relinked_sha256=repaired_fingerprint.sha256,
    )


def _run_handoff_check(
    check_id: str,
    service: ProjectGraphService,
    *,
    check_cancelled: Callable[[], None],
) -> RepositoryCheckEvidence:
    nodes, _handoffs = service.repository.load()
    source = nodes[0]
    specs = {item.workspace_id: item for item in workspace_catalog()}
    source_spec = specs.get(source.workspace)
    if source_spec is None or not source_spec.targets:
        return _failed(check_id, "Project graph source cannot create a handoff")
    target_workspace = source_spec.targets[0]
    output = AssetReference(
        asset_id="parity-returned-output",
        role="parity_output",
        ownership="generated",
        derived_from=tuple(item.asset_id for item in source.assets),
    )
    target = service.upsert_node(
        NodeRequest(
            project_id=source.project_id,
            workspace=target_workspace,
            owner_id="parity-target",
            label="Parity target",
            revision=source.revision + 1,
            assets=(output,),
        )
    )
    handoff = service.create_handoff(
        HandoffRequest(
            project_id=source.project_id,
            source_node_id=source.node_id,
            target_workspace=target_workspace,
            input_asset_ids=tuple(item.asset_id for item in source.assets),
        )
    )
    service.open_handoff(handoff.handoff_id)
    check_cancelled()
    returned = service.return_handoff(
        handoff.handoff_id,
        target_node_id=target.node_id,
        output_asset_ids=(output.asset_id,),
    )
    reopened = ProjectGraphService(service.repository.path).get_handoff(handoff.handoff_id)
    if returned.status != "returned" or reopened != returned:
        return _failed(check_id, "Handoff return did not survive repository reopen")
    return _passed(
        check_id,
        "Handoff opened, returned, and reopened through ProjectGraphService",
        repository="project_graph",
        handoff_id=returned.handoff_id,
        source_revision=returned.source_revision,
        target_revision=target.revision,
    )


def _run_longform_checkpoint_check(
    case_id: str,
    check_id: str,
    source: Path,
    *,
    check_cancelled: Callable[[], None],
) -> RepositoryCheckEvidence:
    source_bytes = _read_file(
        source,
        max_bytes=_MAX_REPOSITORY_FIXTURE_BYTES,
        check_cancelled=check_cancelled,
    )
    source_text = source_bytes.decode("utf-8", errors="replace")
    kind = "audiobook" if case_id.endswith("audiobook") else "stories"
    with tempfile.TemporaryDirectory(prefix="galaxy-parity-longform-") as temporary:
        index = Path(temporary) / "longform.json"
        repository = LongformProjectRepository(index)
        project = LongformProject.create(
            name="Parity checkpoint",
            kind=kind,
            source=source_text,
            document={
                "items": [
                    {"item_id": "1", "text": source_text[:512]},
                    {"item_id": "2", "text": source_text[512:1024] or source_text[:512]},
                ]
            },
            metadata={"source_sha256": sha256(source_bytes).hexdigest()},
        )
        saved = repository.save(project, expected_revision=0)
        checkpointed = repository.save(
            saved.evolved(stage="render", last_result={"completed_item_ids": ["1"]}),
            expected_revision=saved.revision,
        )
        check_cancelled()
        resumed_repository = LongformProjectRepository(index)
        resumed = resumed_repository.get(saved.project_id)
        if resumed is None or resumed.last_result.get("completed_item_ids") != ["1"]:
            return _failed(check_id, "Longform checkpoint could not be reopened")
        completed = resumed_repository.save(
            resumed.evolved(last_result={"completed_item_ids": ["1", "2"]}),
            expected_revision=resumed.revision,
        )
        reopened = LongformProjectRepository(index).get(saved.project_id)
        if (
            reopened is None
            or reopened.source != source_text
            or reopened.revision <= checkpointed.revision
            or reopened.last_result.get("completed_item_ids") != ["1", "2"]
        ):
            return _failed(check_id, "Longform resume did not preserve checkpoint progress")
        return _passed(
            check_id,
            "Longform checkpoint reopened and resumed through LongformProjectRepository",
            repository="longform_project",
            checkpoint_revision=checkpointed.revision,
            completed_revision=completed.revision,
            source_sha256=sha256(source_bytes).hexdigest(),
        )


def _graph_payload(value: object) -> object:
    nodes, handoffs = value  # type: ignore[misc]
    return {
        "nodes": [asdict(item) for item in nodes],
        "handoffs": [asdict(item) for item in handoffs],
    }


def _read_file(
    path: Path,
    *,
    max_bytes: int,
    check_cancelled: Callable[[], None],
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    with path.open("rb") as source:
        while chunk := source.read(_READ_CHUNK_BYTES):
            check_cancelled()
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("repository fixture size limit exceeded")
            chunks.append(chunk)
    return b"".join(chunks)


def _copy_file(
    source: Path,
    destination: Path,
    *,
    max_bytes: int,
    check_cancelled: Callable[[], None],
) -> None:
    total = 0
    with source.open("rb") as input_file, destination.open("wb") as output_file:
        while chunk := input_file.read(_READ_CHUNK_BYTES):
            check_cancelled()
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("repository fixture size limit exceeded")
            output_file.write(chunk)


def _passed(check_id: str, message: str, **measurements: object) -> RepositoryCheckEvidence:
    return RepositoryCheckEvidence(check_id, "pass", message, measurements)


def _failed(check_id: str, message: str) -> RepositoryCheckEvidence:
    return RepositoryCheckEvidence(check_id, "fail", message)


def _blocked(check_id: str, message: str) -> RepositoryCheckEvidence:
    return RepositoryCheckEvidence(check_id, "blocked", message)
