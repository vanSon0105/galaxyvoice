from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import app.parity.validators as validators_module
from app.parity import CaseResult, CheckResult, MediaExpectation, ParityCase
from app.parity.validators import (
    MediaInfo,
    FfprobeMediaProbe,
    PerformanceSample,
    RecoverySample,
    judge_cancellation,
    judge_duration,
    judge_identity_mapping,
    judge_loudness,
    judge_performance,
    judge_recovery,
    judge_subtitles,
    media_matches,
    validate_case,
)


CPU_PERFORMANCE_METRICS = frozenset({"wall_seconds", "peak_ram_bytes"})


def _cpu_performance_sample(
    wall_seconds: float,
    *,
    peak_ram_bytes: int = 1_000,
    response_ms: tuple[float, ...] = (),
) -> PerformanceSample:
    return PerformanceSample(
        wall_seconds=wall_seconds,
        peak_ram_bytes=peak_ram_bytes,
        response_ms=response_ms,
        applicable_metrics=CPU_PERFORMANCE_METRICS,
    )


@pytest.mark.parametrize(
    ("native", "reference", "expected"),
    [
        (10.5, 10.0, "pass"),
        (10.501, 10.0, "fail"),
        (21.0, 20.0, "pass"),
        (21.001, 20.0, "fail"),
    ],
)
def test_duration_uses_larger_of_250ms_or_five_percent(
    native: float,
    reference: float,
    expected: str,
) -> None:
    assert judge_duration(native, reference).status == expected


def test_subtitles_require_exact_count_and_order_after_whitespace_normalization() -> None:
    reference = (
        {"start_ms": 0, "end_ms": 800, "text": "Xin chao"},
        {"start_ms": 900, "end_ms": 1_500, "text": "Galaxy Voice"},
    )

    normalized = (
        {"start_ms": 0, "end_ms": 800, "text": " Xin\u00a0chao "},
        {"start_ms": 900, "end_ms": 1_500, "text": "Galaxy\nVoice"},
    )
    reordered = tuple(reversed(reference))

    assert judge_subtitles(normalized, reference).status == "pass"
    assert judge_subtitles(reordered, reference).status == "fail"
    assert judge_subtitles(reference[:1], reference).status == "fail"


def test_identity_mapping_compares_normalized_ids_not_display_labels() -> None:
    reference = {"speaker_1": "voice.main", "language": "vi-VN"}

    assert (
        judge_identity_mapping(
            {" SPEAKER_1 ": "VOICE.MAIN", "language": "vi-vn"},
            reference,
        ).status
        == "pass"
    )
    assert (
        judge_identity_mapping(
            {"speaker_1": "Narrator", "language": "Vietnamese"},
            reference,
        ).status
        == "fail"
    )


@pytest.mark.parametrize(
    ("measured", "expected"),
    [(-18.0, "pass"), (-14.0, "pass"), (-18.01, "fail"), (-13.99, "fail")],
)
def test_loudness_defaults_to_minus_16_lufs_plus_or_minus_2(
    measured: float,
    expected: str,
) -> None:
    assert judge_loudness(measured).status == expected


def test_missing_reference_metric_is_blocked() -> None:
    result = judge_performance(
        native=PerformanceSample(wall_seconds=1),
        reference=None,
    )

    assert result.status == "blocked"


def test_performance_pins_reference_ratios_and_response_p95() -> None:
    reference = PerformanceSample(
        wall_seconds=100,
        peak_ram_bytes=1_000,
        peak_vram_bytes=2_000,
    )

    assert (
        judge_performance(
            native=PerformanceSample(
                wall_seconds=125,
                peak_ram_bytes=1_250,
                peak_vram_bytes=2_500,
                response_ms=(20, 200, 100),
            ),
            reference=reference,
        ).status
        == "pass"
    )
    assert (
        judge_performance(
            native=_cpu_performance_sample(125.01, response_ms=(1,)),
            reference=_cpu_performance_sample(100),
        ).status
        == "fail"
    )
    assert (
        judge_performance(
            native=_cpu_performance_sample(1, response_ms=(201,)),
            reference=_cpu_performance_sample(1),
        ).status
        == "fail"
    )


def test_performance_blocks_when_a_supported_reference_metric_is_missing() -> None:
    result = judge_performance(
        native=PerformanceSample(wall_seconds=1, peak_ram_bytes=1_000),
        reference=PerformanceSample(wall_seconds=1),
    )

    assert result.status == "blocked"


def test_performance_blocks_when_both_samples_omit_supported_metrics() -> None:
    result = judge_performance(
        native=PerformanceSample(wall_seconds=1, response_ms=(20,)),
        reference=PerformanceSample(wall_seconds=1),
    )

    assert result.status == "blocked"
    assert result.measurements["missing_metrics"] == (
        "peak_ram_bytes",
        "peak_vram_bytes",
    )


def test_performance_sample_declares_applicable_metrics_contract() -> None:
    assert "applicable_metrics" in PerformanceSample.__dataclass_fields__


def test_performance_allows_vram_not_applicable_only_by_matched_contract() -> None:
    cpu_metrics = frozenset({"wall_seconds", "peak_ram_bytes"})
    result = judge_performance(
        native=PerformanceSample(
            wall_seconds=1,
            peak_ram_bytes=1_000,
            response_ms=(20,),
            applicable_metrics=cpu_metrics,
        ),
        reference=PerformanceSample(
            wall_seconds=1,
            peak_ram_bytes=1_000,
            applicable_metrics=cpu_metrics,
        ),
    )

    assert result.status == "pass"
    assert result.measurements["not_applicable_metrics"] == ("peak_vram_bytes",)


@pytest.mark.parametrize(
    "zero_metric",
    ["wall_seconds", "peak_ram_bytes", "peak_vram_bytes"],
)
def test_performance_blocks_zero_native_applicable_metrics(
    zero_metric: str,
) -> None:
    native_values = {
        "wall_seconds": 1,
        "peak_ram_bytes": 1_000,
        "peak_vram_bytes": 2_000,
    }
    native_values[zero_metric] = 0

    result = judge_performance(
        native=PerformanceSample(**native_values, response_ms=(20,)),
        reference=PerformanceSample(
            wall_seconds=1,
            peak_ram_bytes=1_000,
            peak_vram_bytes=2_000,
        ),
    )

    assert result.status == "blocked"
    assert result.measurements["missing_metrics"] == (zero_metric,)


@pytest.mark.parametrize(
    "zero_metric",
    ["wall_seconds", "peak_ram_bytes", "peak_vram_bytes"],
)
def test_performance_blocks_zero_reference_applicable_metrics(
    zero_metric: str,
) -> None:
    reference_values = {
        "wall_seconds": 1,
        "peak_ram_bytes": 1_000,
        "peak_vram_bytes": 2_000,
    }
    reference_values[zero_metric] = 0

    result = judge_performance(
        native=PerformanceSample(
            wall_seconds=1,
            peak_ram_bytes=1_000,
            peak_vram_bytes=2_000,
            response_ms=(20,),
        ),
        reference=PerformanceSample(**reference_values),
    )

    assert result.status == "blocked"
    assert result.measurements["missing_metrics"] == (zero_metric,)


def test_performance_contract_cannot_omit_wall_time_or_ram() -> None:
    wall_only = frozenset({"wall_seconds"})
    result = judge_performance(
        native=PerformanceSample(
            wall_seconds=1,
            response_ms=(20,),
            applicable_metrics=wall_only,
        ),
        reference=PerformanceSample(
            wall_seconds=1,
            applicable_metrics=wall_only,
        ),
    )

    assert result.status == "fail"


def test_performance_blocks_when_response_samples_are_unavailable() -> None:
    result = judge_performance(
        native=_cpu_performance_sample(1),
        reference=_cpu_performance_sample(1),
    )

    assert result.status == "blocked"


@pytest.mark.parametrize(
    ("device", "seconds", "expected"),
    [
        ("cpu", 2.0, "pass"),
        ("cpu", 2.001, "fail"),
        ("cuda", 5.0, "pass"),
        ("mps", 5.001, "fail"),
    ],
)
def test_cancellation_uses_cpu_and_accelerator_thresholds(
    device: str,
    seconds: float,
    expected: str,
) -> None:
    assert judge_cancellation(seconds, device=device).status == expected


def test_cancellation_blocks_when_resolved_device_is_unknown() -> None:
    assert judge_cancellation(1.0, device="unknown").status == "blocked"


def test_recovery_reconciles_interrupted_tasks_and_requires_route_for_resumable() -> None:
    assert (
        judge_recovery(
            RecoverySample(
                interrupted=True,
                task_status="interrupted",
                resumable=True,
                recovery_route="/settings/parity",
            )
        ).status
        == "pass"
    )
    assert (
        judge_recovery(
            RecoverySample(
                interrupted=True,
                task_status="running",
                resumable=True,
                recovery_route="/settings/parity",
            )
        ).status
        == "fail"
    )
    assert (
        judge_recovery(
            RecoverySample(
                interrupted=True,
                task_status="interrupted",
                resumable=True,
                recovery_route=None,
            )
        ).status
        == "fail"
    )
    assert (
        judge_recovery(
            RecoverySample(
                interrupted=False,
                task_status="completed",
                resumable=False,
                recovery_route=None,
            )
        ).status
        == "not_applicable"
    )
    assert (
        judge_recovery(
            RecoverySample(
                interrupted=True,
                task_status=" INTERRUPTED ",
                resumable=True,
                recovery_route="/studio",
            )
        ).status
        == "fail"
    )


def test_recovery_route_policy_cannot_be_redefined_by_evidence() -> None:
    result = judge_recovery(
        RecoverySample(
            interrupted=True,
            task_status="interrupted",
            resumable=True,
            recovery_route="/caller-route",
        )
    )

    assert result.status == "fail"


def test_recovery_evidence_does_not_expose_expected_route_policy() -> None:
    assert "expected_recovery_route" not in RecoverySample.__dataclass_fields__


def test_validate_case_uses_case_subtitle_tolerance_not_measurement_threshold() -> None:
    reference = ({"start_ms": 0, "end_ms": 500, "text": "Hello"},)
    native = ({"start_ms": 51, "end_ms": 551, "text": "Hello"},)
    case = ParityCase(
        case_id="transcripts.multilingual_video",
        area="transcripts",
        title="Timed captions",
        required=True,
        checks=("subtitle_timing",),
        thresholds={"subtitle_timing_tolerance_ms": 50},
    )

    result = validate_case(
        case,
        {},
        probe=_Probe(),
        measurements={
            "subtitle_timing": {
                "native": native,
                "reference": reference,
                "timing_tolerance_ms": 10_000,
            }
        },
    )

    assert result.status == "fail"
    assert result.checks[0].check_id == "subtitle_timing"


class _Probe:
    def inspect(self, path: Path) -> MediaInfo:
        assert path.name == "native.wav"
        return MediaInfo(
            container="wav",
            audio_codec="pcm_s16le",
            audio_streams=1,
            video_streams=0,
            subtitle_streams=0,
            channels=1,
            sample_rate=16_000,
            duration_seconds=1.0,
        )


def test_validate_case_uses_injected_probe_and_pure_judges(tmp_path: Path) -> None:
    media = tmp_path / "native.wav"
    media.touch()
    case = ParityCase(
        case_id="studio.short_tts",
        area="studio",
        title="Short TTS",
        required=True,
        fixture_roles=("short_tts",),
        checks=("output_format", "duration", "loudness"),
    )

    result = validate_case(
        case,
        {"short_tts": media},
        probe=_Probe(),
        measurements={
            "output_format": {
                "role": "short_tts",
                "expected": {
                    "container": "wav",
                    "audio_codec": "pcm_s16le",
                    "audio_streams": 1,
                    "channels": 1,
                    "sample_rate": 16_000,
                },
            },
            "duration": {"native_seconds": 10.25, "reference_seconds": 10.0},
            "loudness": {"measured_lufs": -16.0},
        },
    )

    assert result.status == "pass"
    assert tuple(check.status for check in result.checks) == ("pass", "pass", "pass")


def test_validate_case_preserves_declared_check_ids_for_alias_judges() -> None:
    subtitle_cues = ({"start_ms": 0, "end_ms": 500, "text": "Hello"},)
    performance = PerformanceSample(
        wall_seconds=1,
        peak_ram_bytes=1_000,
        response_ms=(200,),
        applicable_metrics=CPU_PERFORMANCE_METRICS,
    )
    recovery = RecoverySample(
        interrupted=True,
        task_status="interrupted",
        resumable=True,
        recovery_route="/settings/parity",
    )
    check_ids = (
        "subtitle_order",
        "speaker_mapping",
        "interaction_responsiveness",
        "cancellation_acknowledgement",
        "recovery_route",
    )
    case = ParityCase(
        case_id="aliases",
        area="reliability",
        title="Alias judges",
        required=True,
        checks=check_ids,
    )

    result = validate_case(
        case,
        {},
        probe=_Probe(),
        measurements={
            "subtitle_order": {"native": subtitle_cues, "reference": subtitle_cues},
            "speaker_mapping": {
                "native": {"speaker": "voice.main"},
                "reference": {"speaker": "voice.main"},
            },
            "interaction_responsiveness": {
                "native": performance,
                "reference": _cpu_performance_sample(1),
            },
            "cancellation_acknowledgement": {
                "acknowledgement_seconds": 2,
                "device": "cpu",
            },
            "recovery_route": {"sample": recovery},
        },
    )

    assert result.status == "pass"
    assert tuple(check.check_id for check in result.checks) == check_ids


def test_validate_case_supports_output_stream_checks_with_injected_probe(
    tmp_path: Path,
) -> None:
    media = tmp_path / "native.wav"
    media.touch()
    case = ParityCase(
        case_id="dubbing.two_speaker",
        area="dubbing",
        title="Two-speaker dubbing",
        required=True,
        fixture_roles=("mixed_source_audio",),
        checks=("output_streams",),
    )

    result = validate_case(
        case,
        {"mixed_source_audio": media},
        probe=_Probe(),
        measurements={
            "output_streams": {
                "role": "mixed_source_audio",
                "expected": {"audio_streams": 1, "video_streams": 0},
            }
        },
    )

    assert result.status == "pass"
    assert result.checks[0].check_id == "output_streams"


@pytest.mark.parametrize(
    ("extension", "expected_status"),
    [(".wav", "pass"), ("wav", "pass"), (".mp3", "fail")],
)
def test_validate_case_checks_required_output_extension(
    tmp_path: Path,
    extension: str,
    expected_status: str,
) -> None:
    media = tmp_path / "native.wav"
    media.touch()
    case = ParityCase(
        case_id="studio.short_tts",
        area="studio",
        title="Short TTS",
        required=True,
        fixture_roles=("short_tts",),
        checks=("output_format",),
    )

    result = validate_case(
        case,
        {"short_tts": media},
        probe=_Probe(),
        measurements={
            "output_format": {
                "role": "short_tts",
                "expected": {
                    "extension": extension,
                    "container": "wav",
                },
            }
        },
    )

    assert result.status == expected_status


def test_validate_case_cannot_relax_default_thresholds() -> None:
    case = ParityCase(
        case_id="strict-thresholds",
        area="studio",
        title="Strict thresholds",
        required=True,
        checks=("duration", "loudness", "performance", "cancellation_acknowledgement"),
        thresholds={
            "duration_absolute_ms": 10_000,
            "duration_relative_ratio": 1.0,
            "loudness_tolerance_lu": 10.0,
            "reference_performance_ratio": 2.0,
            "interaction_p95_ms": 1_000,
            "cpu_cancellation_seconds": 10.0,
        },
    )

    result = validate_case(
        case,
        {},
        probe=_Probe(),
        measurements={
            "duration": {"native_seconds": 10.501, "reference_seconds": 10.0},
            "loudness": {"measured_lufs": -13.99},
            "performance": {
                "native": _cpu_performance_sample(1.251, response_ms=(201,)),
                "reference": _cpu_performance_sample(1),
            },
            "cancellation_acknowledgement": {
                "acknowledgement_seconds": 2.001,
                "device": "cpu",
            },
        },
    )

    assert result.status == "fail"
    assert tuple(check.status for check in result.checks) == (
        "fail",
        "fail",
        "fail",
        "fail",
    )


def test_validate_case_blocks_only_the_case_with_missing_asset(tmp_path: Path) -> None:
    case = ParityCase(
        case_id="studio.short_tts",
        area="studio",
        title="Short TTS",
        required=True,
        fixture_roles=("short_tts", "short_tts_reference"),
        checks=("duration",),
    )

    result = validate_case(
        case,
        {"short_tts": tmp_path / "native.wav"},
        probe=_Probe(),
        measurements={"duration": {"native_seconds": 1, "reference_seconds": 1}},
    )

    assert result.status == "blocked"
    assert result.checks[0].status == "blocked"


def test_check_result_rejects_status_outside_exact_vocabulary() -> None:
    with pytest.raises(ValueError, match="check status"):
        CheckResult(
            check_id="duration",
            status="ready",  # type: ignore[arg-type]
            message="invalid",
        )


def test_case_result_rejects_status_outside_exact_vocabulary() -> None:
    with pytest.raises(ValueError, match="check status"):
        CaseResult(
            case_id="studio.short_tts",
            status="ready",  # type: ignore[arg-type]
            checks=(),
        )


def test_validate_case_blocks_malformed_measurement_instead_of_raising(
    tmp_path: Path,
) -> None:
    case = ParityCase(
        case_id="studio.short_tts",
        area="studio",
        title="Short TTS",
        required=True,
        checks=("duration",),
    )

    result = validate_case(
        case,
        {},
        probe=_Probe(),
        measurements={"duration": "not-a-measurement-object"},
    )

    assert result.status == "blocked"


def test_validate_case_rejects_precomputed_result_for_core_judge() -> None:
    case = ParityCase(
        case_id="studio.short_tts",
        area="studio",
        title="Short TTS",
        required=True,
        checks=("duration",),
    )

    result = validate_case(
        case,
        {},
        probe=_Probe(),
        measurements={
            "duration": CheckResult(
                check_id="duration",
                status="pass",
                message="caller supplied pass",
            )
        },
    )

    assert result.status == "blocked"
    assert result.checks[0].status == "blocked"


def test_behavioral_checks_have_a_separate_typed_evidence_interface() -> None:
    assert hasattr(validators_module, "BehavioralCheckEvidence")


def test_typed_behavioral_evidence_is_only_accepted_for_non_core_checks() -> None:
    evidence = validators_module.BehavioralCheckEvidence(
        passed=True,
        message="Repository behavior verified",
    )
    behavioral_case = ParityCase(
        case_id="shared.project_portability",
        area="shared",
        title="Project portability",
        required=True,
        checks=("project_reopen",),
    )
    core_case = ParityCase(
        case_id="studio.short_tts",
        area="studio",
        title="Short TTS",
        required=True,
        checks=("duration",),
    )

    behavioral = validate_case(
        behavioral_case,
        {},
        probe=_Probe(),
        measurements={"project_reopen": evidence},
    )
    core = validate_case(
        core_case,
        {},
        probe=_Probe(),
        measurements={"duration": evidence},
    )

    assert behavioral.status == "pass"
    assert behavioral.checks[0].message == "Repository behavior verified"
    assert core.status == "blocked"


def test_bare_boolean_cannot_claim_behavioral_check_pass() -> None:
    case = ParityCase(
        case_id="shared.project_portability",
        area="shared",
        title="Project portability",
        required=True,
        checks=("project_reopen",),
    )

    result = validate_case(
        case,
        {},
        probe=_Probe(),
        measurements={"project_reopen": True},
    )

    assert result.status == "blocked"


def test_pure_judges_fail_closed_for_malformed_nested_objects() -> None:
    assert judge_subtitles((object(),), ()).status == "fail"
    assert judge_identity_mapping(object(), {}).status == "fail"  # type: ignore[arg-type]
    assert judge_performance(native=object(), reference=object()).status == "fail"  # type: ignore[arg-type]
    assert judge_recovery(object()).status == "fail"  # type: ignore[arg-type]


def test_validate_case_fails_closed_for_malformed_threshold() -> None:
    case = ParityCase(
        case_id="studio.short_tts",
        area="studio",
        title="Short TTS",
        required=True,
        checks=("duration",),
        thresholds={"duration_absolute_ms": "not-a-number"},
    )

    result = validate_case(
        case,
        {},
        probe=_Probe(),
        measurements={
            "duration": {"native_seconds": 1.0, "reference_seconds": 1.0}
        },
    )

    assert result.status == "fail"
    assert result.checks[0].status == "fail"


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired("ffprobe", timeout=30),
        RuntimeError("unexpected probe failure"),
    ],
)
def test_validate_case_fails_closed_for_probe_exceptions(
    tmp_path: Path,
    error: Exception,
) -> None:
    class _FailingProbe:
        def inspect(self, path: Path) -> MediaInfo:
            raise error

    media = tmp_path / "native.wav"
    media.touch()
    case = ParityCase(
        case_id="studio.short_tts",
        area="studio",
        title="Short TTS",
        required=True,
        fixture_roles=("short_tts",),
        checks=("output_format",),
    )

    result = validate_case(
        case,
        {"short_tts": media},
        probe=_FailingProbe(),
        measurements={
            "output_format": {
                "role": "short_tts",
                "expected": {"container": "wav"},
            }
        },
    )

    assert result.status == "fail"
    assert result.checks[0].status == "fail"


def test_ffprobe_adapter_uses_existing_locator_and_parses_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _Completed:
        returncode = 0
        stderr = ""
        stdout = (
            '{"format":{"format_name":"mov,mp4,m4a","duration":"2.5"},'
            '"streams":['
            '{"codec_type":"video","codec_name":"h264"},'
            '{"codec_type":"audio","codec_name":"aac","channels":2,'
            '"sample_rate":"48000"}]}'
        )

    monkeypatch.setattr("app.parity.validators.find_ffprobe", lambda: "local-ffprobe")
    monkeypatch.setattr(
        "app.parity.validators.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )

    info = FfprobeMediaProbe().inspect(tmp_path / "sample.mp4")

    assert info.container == "mov,mp4,m4a"
    assert info.video_codec == "h264"
    assert info.audio_codec == "aac"
    assert info.audio_streams == 1
    assert info.video_streams == 1
    assert info.channels == 2
    assert info.sample_rate == 48_000
    assert info.duration_seconds == 2.5
    assert media_matches(info, MediaExpectation(container="mp4")) == ()
