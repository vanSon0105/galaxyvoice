from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .models import AssetReference, HandoffRequest, NodeRequest, ProjectGraphNode
from .service import ProjectGraphService


def register_transcript_handoff(
    service: ProjectGraphService,
    project: Any,
    payload: Mapping[str, Any],
) -> None:
    document_asset_id = f"transcript-document:{project.transcript_id}"
    assets = [
        AssetReference(
            asset_id=document_asset_id,
            role="transcript_document",
            ownership="managed",
            metadata={"cue_count": len(project.cues)},
        )
    ]
    if project.source_path:
        assets.append(
            AssetReference(
                asset_id=f"transcript-source:{project.transcript_id}",
                role="source_media",
                path_hint=project.source_path,
                ownership="linked",
            )
        )
    node = service.upsert_node(
        NodeRequest(
            project_id=project.project_id,
            workspace="transcripts",
            owner_id=project.transcript_id,
            label=project.name,
            revision=int(payload.get("source_revision") or project.revision),
            assets=tuple(assets),
            metadata={"language": payload.get("language", "")},
        )
    )
    service.create_handoff(
        HandoffRequest(
            project_id=project.project_id,
            source_node_id=node.node_id,
            target_workspace=str(payload.get("target") or ""),
            input_asset_ids=(document_asset_id,),
            payload={
                "kind": "transcript_handoff",
                "transcript_id": project.transcript_id,
            },
            handoff_id=str(payload.get("handoff_id") or ""),
        )
    )


def register_longform_project(service: ProjectGraphService, project: Any) -> ProjectGraphNode | None:
    parent_id = str(project.galaxy_project_id or "").strip()
    if not parent_id:
        return None
    document_asset_id = f"longform-document:{project.project_id}"
    assets = [
        AssetReference(
            asset_id=document_asset_id,
            role="longform_document",
            ownership="managed",
            metadata={"kind": project.kind, "stage": project.stage},
        )
    ]
    assets.extend(_result_assets("longform", project.project_id, project.last_result))
    return service.upsert_node(
        NodeRequest(
            project_id=parent_id,
            workspace="longform",
            owner_id=project.project_id,
            label=project.name,
            revision=project.revision,
            assets=tuple(assets),
            metadata={"kind": project.kind, "stage": project.stage},
        )
    )


def register_dubbing_project(service: ProjectGraphService, project: Any) -> ProjectGraphNode | None:
    parent_id = str(project.galaxy_project_id or "").strip()
    if not parent_id:
        return None
    document_asset_id = f"dubbing-document:{project.project_id}"
    assets = [
        AssetReference(
            asset_id=document_asset_id,
            role="dubbing_document",
            ownership="managed",
            metadata={"stage": project.stage, "segment_count": len(project.segments)},
        )
    ]
    for role, path_hint in (
        ("source_video", project.source_video),
        ("source_audio", project.source_audio),
    ):
        if path_hint:
            assets.append(
                AssetReference(
                    asset_id=f"dubbing-{role}:{project.project_id}",
                    role=role,
                    path_hint=path_hint,
                    ownership="linked",
                )
            )
    assets.extend(_result_assets("dubbing", project.project_id, project.last_result))
    return service.upsert_node(
        NodeRequest(
            project_id=parent_id,
            workspace="dubbing",
            owner_id=project.project_id,
            label=project.name,
            revision=project.revision,
            assets=tuple(assets),
            metadata={"stage": project.stage, "language": project.language},
        )
    )


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


def _result_assets(prefix: str, owner_id: str, result: Mapping[str, Any]) -> list[AssetReference]:
    assets: list[AssetReference] = []
    fields = {
        "wav_path": "voice_audio",
        "mp3_path": "voice_audio",
        "m4b_path": "audiobook",
        "mixed_audio_path": "mixed_audio",
        "video_path": "dubbed_video",
        "srt_path": "subtitle",
    }
    document_asset_id = f"{prefix}-document:{owner_id}"
    for field, role in fields.items():
        raw_path = str(result.get(field) or "").strip()
        if not raw_path:
            continue
        suffix = Path(raw_path).suffix.casefold().lstrip(".") or field.removesuffix("_path")
        assets.append(
            AssetReference(
                asset_id=f"{prefix}-output:{owner_id}:{suffix}:{field}",
                role=role,
                path_hint=raw_path,
                ownership="generated",
                derived_from=(document_asset_id,),
            )
        )
    return assets


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
