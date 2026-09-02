"""Typed HTTP adapter for native parity validation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from ... import __version__
from ...common.diagnostics import get_logger, log_operation_failure
from ...parity import (
    ParityNotReadyError,
    ParityRunDetail,
    ParityService,
    SourceChangedError,
    SourceFingerprint,
    StartParityRun,
    ThresholdOverrideRequest,
    UnsafePathError,
    MediaExpectation,
)
from ...parity.evidence import (
    ArtifactCheckEvidence,
    CancellationCheckEvidence,
    DurationCheckEvidence,
    HardwareIdentity,
    IdentityCheckEvidence,
    LoudnessCheckEvidence,
    MediaCheckEvidence,
    MigrationCheckEvidence,
    PerformanceCheckEvidence,
    RecoveryCheckEvidence,
    SubtitleCheckEvidence,
    SubtitleCueEvidence,
)
from ...parity.validators import PerformanceSample, RecoverySample
router = APIRouter(prefix="/api/parity", tags=["parity"])
LOGGER = get_logger("server.parity")

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
FingerprintId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256Text = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonNegativeStrictInt = Annotated[StrictInt, Field(ge=0)]

_INVALID_INPUT_DETAIL = "Dữ liệu parity đầu vào không hợp lệ."
_UNSAFE_PATH_DETAIL = "Đường dẫn parity không được phép."
_IO_FAILURE_DETAIL = "Không thể truy cập dữ liệu parity."
_RUN_NOT_FOUND_DETAIL = "Không tìm thấy lần chạy parity."
_REPORT_NOT_FOUND_DETAIL = "Không tìm thấy báo cáo parity."
_SOURCE_CHANGED_DETAIL = "Nguồn migration đã thay đổi trong lúc kiểm tra."


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SourceFingerprintModel(ResponseModel):
    kind: Literal["file", "directory"]
    sha256: Sha256Text
    byte_size: NonNegativeStrictInt
    entry_count: NonNegativeStrictInt


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
    sandbox_cleaned: bool


class CorpusInspectRequest(RequestModel):
    manifest_path: NonEmptyText
    approved_roots: list[NonEmptyText] = Field(min_length=1)


class MigrationInspectRequest(RequestModel):
    source: NonEmptyText
    approved_roots: list[NonEmptyText] = Field(min_length=1)
    copied_source_confirmed: StrictBool


class SourceFingerprintRequest(RequestModel):
    kind: Literal["file", "directory"]
    sha256: Sha256Text
    byte_size: NonNegativeStrictInt
    entry_count: NonNegativeStrictInt

    @model_validator(mode="after")
    def validate_file_entry_count(self) -> SourceFingerprintRequest:
        if self.kind == "file" and self.entry_count != 1:
            raise ValueError("File fingerprints must contain exactly one entry")
        return self


class ThresholdOverrideBody(RequestModel):
    case_id: NonEmptyText
    threshold_id: NonEmptyText
    value: JsonValue
    provenance: NonEmptyText
    note: NonEmptyText


class HardwareIdentityBody(RequestModel):
    platform: NonEmptyText
    architecture: NonEmptyText
    cpu_model: NonEmptyText
    logical_cpu_count: Annotated[StrictInt, Field(gt=0)]
    memory_bytes: Annotated[StrictInt, Field(gt=0)]
    accelerator_model: str = ""


class PerformanceSampleBody(RequestModel):
    app_version: NonEmptyText
    wall_seconds: Annotated[float, Field(gt=0)]
    peak_ram_bytes: Annotated[StrictInt, Field(gt=0)]
    peak_vram_bytes: Annotated[StrictInt, Field(gt=0)] | None = None
    response_ms: list[Annotated[float, Field(ge=0)]] = Field(min_length=1)
    applicable_metrics: list[
        Literal["wall_seconds", "peak_ram_bytes", "peak_vram_bytes"]
    ] = Field(min_length=2)
    hardware_identity: HardwareIdentityBody
    resolved_device: NonEmptyText

    @model_validator(mode="after")
    def validate_metric_contract(self) -> PerformanceSampleBody:
        metrics = self.applicable_metrics
        if len(metrics) != len(set(metrics)):
            raise ValueError("Performance metrics must be unique")
        if not {"wall_seconds", "peak_ram_bytes"}.issubset(metrics):
            raise ValueError("Wall time and peak RAM must be applicable")
        if ("peak_vram_bytes" in metrics) != (self.peak_vram_bytes is not None):
            raise ValueError("VRAM value and applicability must match")
        return self


class MediaExpectationBody(RequestModel):
    extension: NonEmptyText | None = None
    container: NonEmptyText | None = None
    audio_codec: NonEmptyText | None = None
    video_codec: NonEmptyText | None = None
    audio_streams: NonNegativeStrictInt | None = None
    video_streams: NonNegativeStrictInt | None = None
    subtitle_streams: NonNegativeStrictInt | None = None
    channels: NonNegativeStrictInt | None = None
    sample_rate: NonNegativeStrictInt | None = None
    duration_seconds: Annotated[float, Field(ge=0)] | None = None


class MediaEvidenceBody(RequestModel):
    kind: Literal["media"]
    role: NonEmptyText
    expected: MediaExpectationBody


class DurationEvidenceBody(RequestModel):
    kind: Literal["duration"]
    native_seconds: Annotated[float, Field(ge=0)]
    reference_seconds: Annotated[float, Field(ge=0)]


class SubtitleCueBody(RequestModel):
    start_ms: NonNegativeStrictInt
    end_ms: NonNegativeStrictInt
    text: str


class SubtitleEvidenceBody(RequestModel):
    kind: Literal["subtitles"]
    native: list[SubtitleCueBody]
    reference: list[SubtitleCueBody]


class IdentityEvidenceBody(RequestModel):
    kind: Literal["identity"]
    native: dict[NonEmptyText, NonEmptyText]
    reference: dict[NonEmptyText, NonEmptyText]


class LoudnessEvidenceBody(RequestModel):
    kind: Literal["loudness"]
    measured_lufs: float


class PerformanceEvidenceBody(RequestModel):
    kind: Literal["performance"]
    native: PerformanceSampleBody
    reference: PerformanceSampleBody


class CancellationEvidenceBody(RequestModel):
    kind: Literal["cancellation"]
    acknowledgement_seconds: Annotated[float, Field(ge=0)]
    device: NonEmptyText


class RecoveryEvidenceBody(RequestModel):
    kind: Literal["recovery"]
    interrupted: StrictBool
    task_status: NonEmptyText
    resumable: StrictBool
    recovery_route: NonEmptyText | None = None


class ArtifactEvidenceBody(RequestModel):
    kind: Literal["artifact"]
    role: NonEmptyText
    sha256: Sha256Text


class MigrationEvidenceBody(RequestModel):
    kind: Literal["migration"]
    source_roles: list[NonEmptyText] = Field(min_length=1)
    copied_source_confirmed: StrictBool

    @model_validator(mode="after")
    def validate_unique_roles(self) -> MigrationEvidenceBody:
        if len(self.source_roles) != len(set(self.source_roles)):
            raise ValueError("Migration source roles must be unique")
        if self.copied_source_confirmed is not True:
            raise ValueError("Explicit copied source confirmation is required")
        return self


EvidenceBody = Annotated[
    MediaEvidenceBody
    | DurationEvidenceBody
    | SubtitleEvidenceBody
    | IdentityEvidenceBody
    | LoudnessEvidenceBody
    | PerformanceEvidenceBody
    | CancellationEvidenceBody
    | RecoveryEvidenceBody
    | ArtifactEvidenceBody
    | MigrationEvidenceBody,
    Field(discriminator="kind"),
]


class StartRunRequest(RequestModel):
    manifest_path: NonEmptyText
    approved_roots: list[NonEmptyText] = Field(min_length=1)
    evidence_by_case: dict[NonEmptyText, dict[NonEmptyText, EvidenceBody]] = Field(
        default_factory=dict
    )
    threshold_overrides: list[ThresholdOverrideBody] = Field(default_factory=list)
    source_fingerprints: dict[FingerprintId, SourceFingerprintRequest] = Field(
        default_factory=dict
    )
    reference_fingerprints: dict[FingerprintId, SourceFingerprintRequest] = Field(
        default_factory=dict
    )


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
    report_revision: str


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
    ready_for_acceptance: bool


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


def _hardware(value: HardwareIdentityBody) -> HardwareIdentity:
    return HardwareIdentity(**value.model_dump())


def _performance_sample(value: PerformanceSampleBody) -> PerformanceSample:
    return PerformanceSample(
        app_version=value.app_version,
        wall_seconds=value.wall_seconds,
        peak_ram_bytes=value.peak_ram_bytes,
        peak_vram_bytes=value.peak_vram_bytes,
        response_ms=tuple(value.response_ms),
        applicable_metrics=frozenset(value.applicable_metrics),
        hardware_identity=_hardware(value.hardware_identity),
        resolved_device=value.resolved_device,
    )


def _domain_evidence(value: EvidenceBody) -> object:
    if isinstance(value, MediaEvidenceBody):
        return MediaCheckEvidence(
            role=value.role,
            expected=MediaExpectation(**value.expected.model_dump(exclude_none=True)),
        )
    if isinstance(value, DurationEvidenceBody):
        return DurationCheckEvidence(
            native_seconds=value.native_seconds,
            reference_seconds=value.reference_seconds,
        )
    if isinstance(value, SubtitleEvidenceBody):
        return SubtitleCheckEvidence(
            native=tuple(SubtitleCueEvidence(**item.model_dump()) for item in value.native),
            reference=tuple(
                SubtitleCueEvidence(**item.model_dump()) for item in value.reference
            ),
        )
    if isinstance(value, IdentityEvidenceBody):
        return IdentityCheckEvidence(
            native=dict(value.native),
            reference=dict(value.reference),
        )
    if isinstance(value, LoudnessEvidenceBody):
        return LoudnessCheckEvidence(measured_lufs=value.measured_lufs)
    if isinstance(value, PerformanceEvidenceBody):
        return PerformanceCheckEvidence(
            native=_performance_sample(value.native),
            reference=_performance_sample(value.reference),
        )
    if isinstance(value, CancellationEvidenceBody):
        return CancellationCheckEvidence(
            acknowledgement_seconds=value.acknowledgement_seconds,
            device=value.device,
        )
    if isinstance(value, RecoveryEvidenceBody):
        return RecoveryCheckEvidence(
            sample=RecoverySample(
                interrupted=value.interrupted,
                task_status=value.task_status,
                resumable=value.resumable,
                recovery_route=value.recovery_route,
            ),
        )
    if isinstance(value, ArtifactEvidenceBody):
        return ArtifactCheckEvidence(role=value.role, sha256=value.sha256)
    if isinstance(value, MigrationEvidenceBody):
        return MigrationCheckEvidence(
            source_roles=tuple(value.source_roles),
            copied_source_confirmed=value.copied_source_confirmed,
        )
    raise TypeError("Unknown parity evidence contract")


def _input_failure(error: Exception, operation: str) -> NoReturn:
    os_error = _caused_os_error(error)
    if os_error is not None and not isinstance(os_error, FileNotFoundError):
        log_operation_failure(LOGGER, operation, os_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_IO_FAILURE_DETAIL,
        ) from error
    detail = (
        _UNSAFE_PATH_DETAIL
        if isinstance(error, UnsafePathError)
        else _INVALID_INPUT_DETAIL
    )
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=detail,
    ) from error


def _io_failure(error: OSError, operation: str) -> NoReturn:
    log_operation_failure(LOGGER, operation, error)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=_IO_FAILURE_DETAIL,
    ) from error


def _caused_os_error(error: BaseException) -> OSError | None:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _run_response(detail: ParityRunDetail) -> ParityRunResponse:
    return ParityRunResponse.model_validate(
        {
            **detail.run.__dict__,
            "ready_for_acceptance": detail.ready_for_acceptance,
        }
    )


def _run_detail(service: ParityService, run_id: str) -> ParityRunDetail:
    detail = service.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_RUN_NOT_FOUND_DETAIL,
        )
    return detail


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
        _input_failure(error, "parity corpus inspection")
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_SOURCE_CHANGED_DETAIL,
        ) from error
    except (FileNotFoundError, OSError, UnsafePathError, ValueError) as error:
        _input_failure(error, "parity migration inspection")
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
        measurements_by_case={
            case_id: {
                check_id: _domain_evidence(evidence)
                for check_id, evidence in checks.items()
            }
            for case_id, checks in body.evidence_by_case.items()
        },
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
        _input_failure(error, "parity run start")
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
    service = _service(request)
    return _run_response(_run_detail(service, run_id))


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_REPORT_NOT_FOUND_DETAIL,
        ) from error
    except OSError as error:
        _io_failure(error, "parity report read")
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
            detail=_RUN_NOT_FOUND_DETAIL,
        ) from error
    except ParityNotReadyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        _input_failure(error, "parity manual evidence")
    service = _service(request)
    return _run_response(_run_detail(service, run.run_id))


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
            detail=_RUN_NOT_FOUND_DETAIL,
        ) from error
    except ParityNotReadyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        _input_failure(error, "parity acceptance")
    service = _service(request)
    return _run_response(_run_detail(service, run.run_id))
