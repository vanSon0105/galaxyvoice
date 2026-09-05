from __future__ import annotations

from typing import Any, Mapping

from .models import AssetReference, NodeRequest, ProjectGraphNode
from .service import ProjectGraphService


def register_studio_take(service: ProjectGraphService, view: Any) -> ProjectGraphNode | None:
    take = view.take
    project_id = str(take.project_id or "").strip()
    if not project_id:
        return None
    outputs = (
        ("voice_wav", take.wav_path),
        ("voice_mp3", take.mp3_path),
        ("manifest", take.manifest_path),
    )
    assets = _generated_assets("studio", take.take_id, (), outputs)
    return service.upsert_node(
        NodeRequest(
            project_id=project_id,
            workspace="studio",
            owner_id=take.take_id,
            label=take.title,
            revision=1,
            assets=tuple(assets),
            metadata={"engine_id": take.engine_id, "language": take.spec.language},
        )
    )


def register_batch_run(service: ProjectGraphService, run: Any) -> ProjectGraphNode | None:
    project_id = str(run.spec.project_id or "").strip()
    if not project_id:
        return None
    document_asset_id = f"batch-document:{run.batch_id}"
    assets = [
        AssetReference(
            asset_id=document_asset_id,
            role="batch_document",
            ownership="managed",
            metadata={"item_count": len(run.items)},
        )
    ]
    outputs: list[tuple[str, str]] = [
        ("combined_wav", run.combined_wav_path),
        ("combined_mp3", run.combined_mp3_path),
        ("manifest", run.manifest_path),
    ]
    for item in run.items:
        outputs.extend(
            (
                (f"item_{item.spec.item_id}_wav", item.wav_path),
                (f"item_{item.spec.item_id}_mp3", item.mp3_path),
            )
        )
    assets.extend(
        _generated_assets(
            "batch",
            run.batch_id,
            (document_asset_id,),
            tuple(outputs),
        )
    )
    return service.upsert_node(
        NodeRequest(
            project_id=project_id,
            workspace="batch",
            owner_id=run.batch_id,
            label=run.spec.title,
            revision=max(1, int(run.completed_count) + int(run.failed_count)),
            assets=tuple(assets),
            metadata={"status": run.status, "engine_id": run.spec.engine_id},
        )
    )


def register_voice_pin(
    service: ProjectGraphService,
    voice: Any,
    pin: Mapping[str, Any],
) -> ProjectGraphNode | None:
    project_id = str(pin.get("project_id") or "").strip()
    snapshot_path = str(pin.get("snapshot_path") or "").strip()
    if not project_id or not snapshot_path:
        return None
    return service.upsert_node(
        NodeRequest(
            project_id=project_id,
            workspace="library",
            owner_id=f"{project_id}:{voice.voice_id}",
            label=str(voice.name),
            revision=max(1, int(voice.revision)),
            assets=(
                AssetReference(
                    asset_id=f"voice-snapshot:{voice.voice_id}",
                    role="pinned_voice_snapshot",
                    path_hint=snapshot_path,
                    ownership="managed",
                    fingerprint=str(pin.get("fingerprint") or ""),
                    metadata={"source": voice.source, "engine_id": voice.engine_id},
                ),
            ),
            metadata={"language": voice.language, "source": voice.source},
        )
    )


def register_media_result(
    service: ProjectGraphService,
    *,
    project_id: str,
    workspace: str,
    owner_id: str,
    label: str,
    sources: tuple[tuple[str, str], ...],
    outputs: tuple[tuple[str, str], ...],
    metadata: Mapping[str, Any] | None = None,
) -> ProjectGraphNode | None:
    parent_id = project_id.strip()
    if not parent_id:
        return None
    source_assets: list[AssetReference] = []
    for role, raw_path in sources:
        path_hint = str(raw_path or "").strip()
        if path_hint:
            source_assets.append(
                AssetReference(
                    asset_id=f"{workspace}-source:{owner_id}:{role}",
                    role=role,
                    path_hint=path_hint,
                    ownership="linked",
                )
            )
    source_ids = tuple(item.asset_id for item in source_assets)
    assets = [
        *source_assets,
        *_generated_assets(workspace, owner_id, source_ids, outputs),
    ]
    return service.upsert_node(
        NodeRequest(
            project_id=parent_id,
            workspace=workspace,
            owner_id=owner_id,
            label=label.strip() or workspace,
            revision=1,
            assets=tuple(assets),
            metadata=metadata or {},
        )
    )


def _generated_assets(
    prefix: str,
    owner_id: str,
    derived_from: tuple[str, ...],
    outputs: tuple[tuple[str, str], ...],
) -> list[AssetReference]:
    assets: list[AssetReference] = []
    for role, raw_path in outputs:
        path_hint = str(raw_path or "").strip()
        if not path_hint:
            continue
        assets.append(
            AssetReference(
                asset_id=f"{prefix}-output:{owner_id}:{role}",
                role=role,
                path_hint=path_hint,
                ownership="generated",
                derived_from=derived_from,
            )
        )
    return assets
