from __future__ import annotations

from typing import Any, Mapping

from .editable import EditableLongformDocument
from .longform import LongformPlan
from .longform_project import LongformProject, LongformProjectRepository


def create_longform_document(
    *,
    kind: str,
    source: str = "",
    payload: Mapping[str, Any] | None = None,
    language: str = "auto",
) -> EditableLongformDocument:
    if kind not in {"stories", "audiobook"}:
        raise ValueError(f"Unsupported long-form workspace: {kind}")
    if payload:
        document = EditableLongformDocument.from_payload(dict(payload), language=language)
        if kind == "audiobook":
            document.assign_default_speaker("Người kể")
        return document
    if kind == "stories":
        return EditableLongformDocument.from_story(source, language=language)
    return EditableLongformDocument.from_audiobook(source, language=language)


def save_longform_project(
    repository: LongformProjectRepository,
    *,
    galaxy_project_id: str,
    project_id: str,
    expected_revision: int,
    name: str,
    kind: str,
    stage: str,
    source: str,
    document: Mapping[str, Any],
    language: str,
    options: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> LongformProject:
    document_payload = dict(document)
    if not document_payload and source.strip():
        document_payload = create_longform_document(
            kind=kind,
            source=source,
            language=language,
        ).to_payload()
    if project_id:
        existing = repository.get(project_id)
        if existing is None:
            raise KeyError(project_id)
        project = existing.evolved(
            galaxy_project_id=galaxy_project_id.strip() or existing.galaxy_project_id,
            name=name.strip() or existing.name,
            kind=kind,
            stage=stage,
            source=source,
            document=document_payload,
            language=language.strip() or "vi",
            options=options,
            metadata=metadata,
            last_result=existing.last_result,
        )
    else:
        project = LongformProject.create(
            galaxy_project_id=galaxy_project_id,
            name=name,
            kind=kind,
            source=source,
            document=document_payload,
            language=language,
            options=options,
            metadata=metadata,
        )
        if stage != project.stage:
            project = project.evolved(stage=stage)
    return repository.save(project, expected_revision=expected_revision)


def document_from_project(project: LongformProject) -> EditableLongformDocument:
    return EditableLongformDocument.from_payload(
        dict(project.document),
        language=project.language,
    )


def preview_plan(plan: LongformPlan, item_index: int) -> LongformPlan:
    source_index = int(item_index) + 1
    spans = tuple(
        span
        for span in plan.spans
        if span.source_index == source_index
    )
    if not spans:
        raise KeyError(source_index)
    return LongformPlan(
        spans=spans,
        chapters=tuple(dict.fromkeys(span.chapter for span in spans if span.chapter)),
        issues=plan.issues,
    )


def attach_longform_result(
    repository: LongformProjectRepository,
    project_id: str,
    payload: Mapping[str, Any],
) -> LongformProject | None:
    project = repository.get(project_id)
    if project is None:
        return None
    return repository.save(
        project.evolved(stage="export", last_result=payload),
        expected_revision=project.revision,
    )
