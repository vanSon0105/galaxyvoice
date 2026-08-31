"""Typed HTTP adapter for native parity validation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StringConstraints,
)

from ... import __version__
from ...parity import (
    ParityNotReadyError,
    ParityService,
    SourceChangedError,
    SourceFingerprint,
    StartParityRun,
    ThresholdOverrideRequest,
    UnsafePathError,
)
from ...parity.repository import ParityRun


router = APIRouter(prefix="/api/parity", tags=["parity"])

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SourceFingerprintModel(ResponseModel):
    kind: str
    sha256: str
    byte_size: int
    entry_count: int


class ParityCaseResponse(ResponseModel):
    case_id: str
    area: str
    title: str
    required: bool
    fixture_roles: list[str]
    checks: list[str]
    manual_prompts: list[str]
    thresholds: dict[str, JsonValue]


class CatalogueResponse(ResponseModel):
    version: str
    cases: list[ParityCaseResponse]


class FindingResponse(ResponseModel):
    code: str
    message: str


class MediaExpectationResponse(ResponseModel):
    extension: str | None
    container: str | None
    audio_codec: str | None
    video_codec: str | None
    audio_streams: int | None
    video_streams: int | None
    subtitle_streams: int | None
    channels: int | None
    sample_rate: int | None
    duration_seconds: float | None


class ManifestAssetResponse(ResponseModel):
    role: str
    path: str
    sha256: str
    byte_size: int
    media: MediaExpectationResponse | None


class ManifestCaseResponse(ResponseModel):
    case_id: str
    assets: list[ManifestAssetResponse]


class FixtureManifestResponse(ResponseModel):
    schema_version: int
    corpus_id: str
    created_at: str
    cases: list[ManifestCaseResponse]


class MediaInfoResponse(ResponseModel):
    container: str
    audio_codec: str | None
    video_codec: str | None
    audio_streams: int
    video_streams: int
    subtitle_streams: int
    channels: int | None
    sample_rate: int | None
    duration_seconds: float | None


class AssetInspectionResponse(ResponseModel):
    role: str
    path: Path | None
    status: Literal[
        "ready",
        "missing",
        "checksum_mismatch",
        "unsupported",
        "unsafe_path",
    ]
    findings: list[FindingResponse]
    media: MediaInfoResponse | None


class CorpusInspectionResponse(ResponseModel):
    manifest: FixtureManifestResponse
    assets_by_role: dict[str, AssetInspectionResponse]
    roles_by_case: dict[str, list[str]]


class ConsentResponse(ResponseModel):
    confirmed: bool
    basis: str
    statement: str
    recorded_at: str
    provenance: str


class MigrationAssetResponse(ResponseModel):
    role: str
    hint: str
    state: Literal["managed", "linked", "missing", "unsafe"]
    expected_sha256: str
    byte_size: int


class MigrationCandidateResponse(ResponseModel):
    source_id: str
    target: str
    data: dict[str, JsonValue]
    assets: list[MigrationAssetResponse]
    warnings: list[str]
    consent: ConsentResponse


class MigrationFindingResponse(ResponseModel):
    source: str
    reason: str


class MigrationInspectionResponse(ResponseModel):
    source_before: SourceFingerprintModel
    source_after: SourceFingerprintModel
    voice_profiles: list[MigrationCandidateResponse]
    persona_bundles: list[MigrationCandidateResponse]
    generation_history: list[MigrationCandidateResponse]
    dub_history: list[MigrationCandidateResponse]
    studio_projects: list[MigrationCandidateResponse]
    export_history: list[MigrationCandidateResponse]
    glossary_terms: list[MigrationCandidateResponse]
    pronunciation_entries: list[MigrationCandidateResponse]
    discovered_documents: list[MigrationCandidateResponse]
    assets: list[MigrationAssetResponse]
    unsupported: list[MigrationFindingResponse]
    warnings: list[str]


class CorpusInspectRequest(RequestModel):
    manifest_path: NonEmptyText
    approved_roots: list[NonEmptyText] = Field(min_length=1)


class MigrationInspectRequest(RequestModel):
    source: NonEmptyText
    approved_roots: list[NonEmptyText] = Field(min_length=1)
    copied_source_confirmed: StrictBool


class SourceFingerprintRequest(RequestModel):
    kind: NonEmptyText
    sha256: NonEmptyText
    byte_size: int = Field(ge=0)
    entry_count: int = Field(ge=0)


class ThresholdOverrideBody(RequestModel):
    case_id: NonEmptyText
    threshold_id: NonEmptyText
    value: JsonValue
    provenance: NonEmptyText
    note: NonEmptyText


class StartRunRequest(RequestModel):
    manifest_path: NonEmptyText
    approved_roots: list[NonEmptyText] = Field(min_length=1)
    measurements_by_case: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    threshold_overrides: list[ThresholdOverrideBody] = Field(default_factory=list)
    source_fingerprints: dict[str, SourceFingerprintRequest] = Field(default_factory=dict)
    reference_fingerprints: dict[str, SourceFingerprintRequest] = Field(default_factory=dict)


class StartRunResponse(ResponseModel):
    task_id: str
    run_id: str


class CheckResultResponse(ResponseModel):
    check_id: str
    status: Literal["pass", "fail", "blocked", "manual_pending", "not_applicable"]
    message: str
    measurements: dict[str, JsonValue]


class CaseResultResponse(ResponseModel):
    case_id: str
    status: Literal["pass", "fail", "blocked", "manual_pending", "not_applicable"]
    checks: list[CheckResultResponse]


class ManualItemResponse(ResponseModel):
    item_id: str
    case_id: str
    prompt: str
    required: bool


class ManualAnswerResponse(ResponseModel):
    item_id: str
    accepted: bool
    note: str
    answered_at: str


class ThresholdOverrideResponse(ResponseModel):
    case_id: str
    threshold_id: str
    catalogue_value: JsonValue
    override_value: JsonValue
    provenance: str
    note: str
    relaxation: bool


class AcceptanceResponse(ResponseModel):
    note: str
    accepted_at: str
    catalogue_hash: str
    manifest_hash: str
    run_revision: str
    manual_revision: str
    input_revision: str


class ParityRunResponse(ResponseModel):
    run_id: str
    task_id: str
    status: Literal["running", "completed", "failed", "cancelled", "interrupted"]
    catalogue_version: str
    catalogue_hash: str
    manifest_path: str
    manifest_hash: str
    manifest_snapshot_path: str
    app_version: str
    created_at: str
    report_json_path: str
    report_markdown_path: str
    required_case_ids: list[str]
    manual_items: list[ManualItemResponse]
    thresholds: dict[str, dict[str, JsonValue]]
    threshold_overrides: list[ThresholdOverrideResponse]
    source_fingerprints: dict[str, SourceFingerprintModel]
    reference_fingerprints: dict[str, SourceFingerprintModel]
    case_results: list[CaseResultResponse]
    warnings: list[str]
    completed_at: str | None
    manual_answers: dict[str, ManualAnswerResponse]
    acceptance: AcceptanceResponse | None


class ParityRunSummaryResponse(ResponseModel):
    run_id: str
    task_id: str
    status: Literal["running", "completed", "failed", "cancelled", "interrupted"]
    catalogue_version: str
    app_version: str
    created_at: str
    completed_at: str | None
    accepted: bool


class ParityRunsResponse(ResponseModel):
    runs: list[ParityRunSummaryResponse]


class ManualAnswerRequest(RequestModel):
    accepted: StrictBool
    note: NonEmptyText


class AcceptanceRequest(RequestModel):
    note: NonEmptyText


def _service(request: Request) -> ParityService:
    return request.app.state.parity_service


def _approved_roots(values: list[str]) -> tuple[Path, ...]:
    return tuple(Path(value) for value in values)


def _unprocessable(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(error),
    )


def _run_response(run: ParityRun) -> ParityRunResponse:
    return ParityRunResponse.model_validate(run)


@router.get("/catalogue", response_model=CatalogueResponse)
def catalogue(request: Request) -> CatalogueResponse:
    return CatalogueResponse.model_validate(_service(request).list_catalogue())


@router.post("/corpus/inspect", response_model=CorpusInspectionResponse)
def inspect_corpus(body: CorpusInspectRequest, request: Request) -> CorpusInspectionResponse:
    try:
        result = _service(request).inspect_corpus(
            Path(body.manifest_path),
            approved_roots=_approved_roots(body.approved_roots),
        )
    except (FileNotFoundError, OSError, UnsafePathError, ValueError) as error:
        raise _unprocessable(error) from error
    return CorpusInspectionResponse.model_validate(result)


@router.post("/migration/inspect", response_model=MigrationInspectionResponse)
def inspect_migration(
    body: MigrationInspectRequest,
    request: Request,
) -> MigrationInspectionResponse:
    try:
        result = _service(request).inspect_migration(
            Path(body.source),
            approved_roots=_approved_roots(body.approved_roots),
            copied_source_confirmed=body.copied_source_confirmed,
        )
    except SourceChangedError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (FileNotFoundError, OSError, UnsafePathError, ValueError) as error:
        raise _unprocessable(error) from error
    return MigrationInspectionResponse.model_validate(result)


@router.post(
    "/runs",
    response_model=StartRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_run(body: StartRunRequest, request: Request) -> StartRunResponse:
    domain_request = StartParityRun(
        manifest_path=Path(body.manifest_path),
        approved_roots=_approved_roots(body.approved_roots),
        app_version=__version__,
        measurements_by_case=body.measurements_by_case,
        threshold_overrides=tuple(
            ThresholdOverrideRequest(**item.model_dump()) for item in body.threshold_overrides
        ),
        source_fingerprints={
            key: SourceFingerprint(**value.model_dump())
            for key, value in body.source_fingerprints.items()
        },
        reference_fingerprints={
            key: SourceFingerprint(**value.model_dump())
            for key, value in body.reference_fingerprints.items()
        },
    )
    try:
        task = _service(request).start_run(domain_request)
    except (FileNotFoundError, OSError, UnsafePathError, ValueError) as error:
        raise _unprocessable(error) from error
    return StartRunResponse(task_id=task.task_id, run_id=task.run_id)


@router.get("/runs", response_model=ParityRunsResponse)
def list_runs(request: Request) -> ParityRunsResponse:
    return ParityRunsResponse(
        runs=[
            ParityRunSummaryResponse(
                run_id=run.run_id,
                task_id=run.task_id,
                status=run.status,
                catalogue_version=run.catalogue_version,
                app_version=run.app_version,
                created_at=run.created_at,
                completed_at=run.completed_at,
                accepted=run.acceptance is not None,
            )
            for run in _service(request).list_runs()
        ]
    )


@router.get("/runs/{run_id}", response_model=ParityRunResponse)
def get_run(run_id: str, request: Request) -> ParityRunResponse:
    run = _service(request).get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parity run not found",
        )
    return _run_response(run)


@router.get(
    "/runs/{run_id}/report",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/json": {"schema": {"type": "object"}},
                "text/markdown": {"schema": {"type": "string"}},
            }
        }
    },
)
def report(
    run_id: str,
    request: Request,
    report_format: Annotated[Literal["json", "markdown"], Query(alias="format")] = "json",
) -> Response:
    try:
        content = _service(request).read_report(run_id, report_format)
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    media_type = "application/json" if report_format == "json" else "text/markdown"
    return Response(content=content, media_type=media_type)


@router.post(
    "/runs/{run_id}/manual-items/{item_id}",
    response_model=ParityRunResponse,
)
def record_manual_item(
    run_id: str,
    item_id: str,
    body: ManualAnswerRequest,
    request: Request,
) -> ParityRunResponse:
    try:
        run = _service(request).record_manual_item(
            run_id,
            item_id,
            accepted=body.accepted,
            note=body.note,
        )
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parity run or item not found",
        ) from error
    except ParityNotReadyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise _unprocessable(error) from error
    return _run_response(run)


@router.post("/runs/{run_id}/accept", response_model=ParityRunResponse)
def accept_run(
    run_id: str,
    body: AcceptanceRequest,
    request: Request,
) -> ParityRunResponse:
    try:
        run = _service(request).accept_run(run_id, note=body.note)
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parity run not found",
        ) from error
    except ParityNotReadyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise _unprocessable(error) from error
    return _run_response(run)
