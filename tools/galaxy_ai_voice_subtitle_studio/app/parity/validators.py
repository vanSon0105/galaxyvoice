"""Deterministic parity judges and injectable local media probing."""

from __future__ import annotations

import json
import math
import sqlite3
import subprocess
import unicodedata
import wave
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..common.ffmpeg import find_ffprobe
from .models import (
    CaseResult,
    CheckResult,
    CheckStatus,
    MediaExpectation,
    MediaInfo,
    ParityCase,
)


DEFAULT_DURATION_ABSOLUTE_MS = 250.0
DEFAULT_DURATION_RELATIVE_RATIO = 0.05
DEFAULT_LOUDNESS_TARGET_LUFS = -16.0
DEFAULT_LOUDNESS_TOLERANCE_LU = 2.0
DEFAULT_PERFORMANCE_RATIO = 1.25
DEFAULT_RESPONSE_P95_MS = 200.0
DEFAULT_CPU_CANCELLATION_SECONDS = 2.0
DEFAULT_ACCELERATOR_CANCELLATION_SECONDS = 5.0
_JSON_SUFFIXES = frozenset({".json"})
_SQLITE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
_TEXT_SUFFIXES = frozenset({".csv", ".md", ".srt", ".tsv", ".txt", ".vtt"})
_ZIP_SUFFIXES = frozenset({".galaxyvoice", ".omnivoice", ".ovsvoice", ".zip"})


class MediaProbe(Protocol):
    def inspect(self, path: Path) -> MediaInfo: ...


class MediaProbeUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PerformanceSample:
    wall_seconds: float
    peak_ram_bytes: int | None = None
    peak_vram_bytes: int | None = None
    response_ms: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "response_ms", tuple(self.response_ms))


@dataclass(frozen=True)
class RecoverySample:
    interrupted: bool
    task_status: str
    resumable: bool
    recovery_route: str | None
    expected_recovery_route: str | None = "/settings/parity"


class DefaultMediaProbe:
    """Use the standard library for WAV and ffprobe for other media."""

    def inspect(self, path: Path) -> MediaInfo:
        suffix = path.suffix.casefold()
        if suffix in {".wav", ".wave"}:
            return _inspect_wav(path)
        if suffix in _JSON_SUFFIXES:
            return _inspect_json(path)
        if suffix in _SQLITE_SUFFIXES:
            return _inspect_sqlite(path)
        if suffix in _TEXT_SUFFIXES:
            return _inspect_text(path)
        if suffix in _ZIP_SUFFIXES:
            return _inspect_zip(path)
        return FfprobeMediaProbe().inspect(path)


class FfprobeMediaProbe:
    def inspect(self, path: Path) -> MediaInfo:
        executable = find_ffprobe()
        if executable is None:
            raise MediaProbeUnavailable("ffprobe is required to inspect this media asset")
        completed = subprocess.run(
            [
                executable,
                "-v",
                "error",
                "-show_entries",
                "format=format_name,duration:stream=codec_type,codec_name,channels,sample_rate",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "ffprobe could not inspect media"
            raise ValueError(detail)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValueError("ffprobe returned invalid JSON") from error
        return _media_info_from_ffprobe(payload)


def judge_duration(
    native_seconds: float | None,
    reference_seconds: float | None,
    *,
    absolute_ms: float = DEFAULT_DURATION_ABSOLUTE_MS,
    relative_ratio: float = DEFAULT_DURATION_RELATIVE_RATIO,
) -> CheckResult:
    values = (native_seconds, reference_seconds, absolute_ms, relative_ratio)
    if native_seconds is None or reference_seconds is None:
        return _result("duration", "blocked", "Native and reference durations are required")
    if not all(_finite_number(value) for value in values) or min(values) < 0:
        return _result("duration", "fail", "Duration measurements and thresholds must be finite and non-negative")
    tolerance_seconds = max(absolute_ms / 1000.0, reference_seconds * relative_ratio)
    delta_seconds = abs(native_seconds - reference_seconds)
    status: CheckStatus = "pass" if delta_seconds <= tolerance_seconds else "fail"
    return _result(
        "duration",
        status,
        "Duration is within tolerance" if status == "pass" else "Duration exceeds tolerance",
        native_seconds=native_seconds,
        reference_seconds=reference_seconds,
        delta_seconds=delta_seconds,
        tolerance_seconds=tolerance_seconds,
    )


def judge_subtitles(
    native: Sequence[Any] | None,
    reference: Sequence[Any] | None,
    *,
    timing_tolerance_ms: float = 0,
) -> CheckResult:
    if native is None or reference is None:
        return _result("subtitles", "blocked", "Native and reference subtitle cues are required")
    if not _finite_number(timing_tolerance_ms) or timing_tolerance_ms < 0:
        return _result(
            "subtitles",
            "fail",
            "Subtitle timing tolerance must be finite and non-negative",
        )
    try:
        native_cues = tuple(_subtitle_cue(cue) for cue in native)
        reference_cues = tuple(_subtitle_cue(cue) for cue in reference)
    except (KeyError, TypeError, ValueError) as error:
        return _result("subtitles", "fail", f"Invalid subtitle cue: {error}")
    if len(native_cues) != len(reference_cues):
        return _result(
            "subtitles",
            "fail",
            "Subtitle cue count differs",
            native_count=len(native_cues),
            reference_count=len(reference_cues),
        )
    for index, (native_cue, reference_cue) in enumerate(
        zip(native_cues, reference_cues, strict=True)
    ):
        text_matches = native_cue[2] == reference_cue[2]
        timing_matches = (
            abs(native_cue[0] - reference_cue[0]) <= timing_tolerance_ms
            and abs(native_cue[1] - reference_cue[1]) <= timing_tolerance_ms
        )
        if not text_matches or not timing_matches:
            return _result(
                "subtitles",
                "fail",
                f"Subtitle cue {index} differs in order, text, or timing",
            )
    return _result("subtitles", "pass", "Subtitle cue count, order, text, and timing match")


def judge_identity_mapping(
    native: Mapping[str, str] | None,
    reference: Mapping[str, str] | None,
) -> CheckResult:
    if native is None or reference is None:
        return _result("identity_mapping", "blocked", "Native and reference identity mappings are required")
    try:
        normalized_native = _normalize_identity_mapping(native)
        normalized_reference = _normalize_identity_mapping(reference)
    except (TypeError, ValueError) as error:
        return _result("identity_mapping", "fail", f"Invalid identity mapping: {error}")
    status: CheckStatus = "pass" if normalized_native == normalized_reference else "fail"
    return _result(
        "identity_mapping",
        status,
        "Normalized identity IDs match" if status == "pass" else "Normalized identity IDs differ",
    )


def judge_loudness(
    measured_lufs: float | None,
    *,
    target_lufs: float = DEFAULT_LOUDNESS_TARGET_LUFS,
    tolerance_lu: float = DEFAULT_LOUDNESS_TOLERANCE_LU,
) -> CheckResult:
    if measured_lufs is None:
        return _result("loudness", "blocked", "Loudness measurement is required")
    if not all(_finite_number(value) for value in (measured_lufs, target_lufs, tolerance_lu)) or tolerance_lu < 0:
        return _result("loudness", "fail", "Loudness values must be finite and tolerance non-negative")
    delta_lu = abs(measured_lufs - target_lufs)
    status: CheckStatus = "pass" if delta_lu <= tolerance_lu else "fail"
    return _result(
        "loudness",
        status,
        "Loudness is within tolerance" if status == "pass" else "Loudness exceeds tolerance",
        measured_lufs=measured_lufs,
        target_lufs=target_lufs,
        tolerance_lu=tolerance_lu,
    )


def judge_performance(
    *,
    native: PerformanceSample | None,
    reference: PerformanceSample | None,
    max_ratio: float = DEFAULT_PERFORMANCE_RATIO,
    max_response_p95_ms: float = DEFAULT_RESPONSE_P95_MS,
) -> CheckResult:
    if native is None or reference is None:
        return _result("performance", "blocked", "Matched native and reference performance samples are required")
    if not _finite_number(max_ratio) or max_ratio <= 0 or not _finite_number(max_response_p95_ms) or max_response_p95_ms < 0:
        return _result("performance", "fail", "Performance thresholds are invalid")
    ratios: dict[str, float] = {}
    for name in ("wall_seconds", "peak_ram_bytes", "peak_vram_bytes"):
        native_value = getattr(native, name)
        reference_value = getattr(reference, name)
        if native_value is None and reference_value is None:
            continue
        if native_value is None or reference_value is None:
            return _result("performance", "blocked", f"Matched reference metric is missing: {name}")
        if not _finite_number(native_value) or not _finite_number(reference_value) or native_value < 0 or reference_value <= 0:
            return _result("performance", "fail", f"Performance metric is invalid: {name}")
        ratios[name] = native_value / reference_value
    if not ratios:
        return _result("performance", "blocked", "No supported performance metric is available")
    if not native.response_ms:
        return _result(
            "performance",
            "blocked",
            "Foreground response samples are required",
        )
    if any(not _finite_number(sample) or sample < 0 for sample in native.response_ms):
        return _result(
            "performance",
            "fail",
            "Response samples must be finite and non-negative",
        )
    response_p95 = _percentile_95(native.response_ms)
    passes = all(ratio <= max_ratio for ratio in ratios.values()) and (
        response_p95 is None or response_p95 <= max_response_p95_ms
    )
    status: CheckStatus = "pass" if passes else "fail"
    measurements: dict[str, object] = {
        "ratios": ratios,
        "max_ratio": max_ratio,
        "max_response_p95_ms": max_response_p95_ms,
    }
    measurements["response_p95_ms"] = response_p95
    return _result(
        "performance",
        status,
        "Performance meets thresholds" if status == "pass" else "Performance exceeds thresholds",
        **measurements,
    )


def judge_cancellation(
    acknowledgement_seconds: float | None,
    *,
    device: str,
    cpu_seconds: float = DEFAULT_CPU_CANCELLATION_SECONDS,
    accelerator_seconds: float = DEFAULT_ACCELERATOR_CANCELLATION_SECONDS,
) -> CheckResult:
    if acknowledgement_seconds is None:
        return _result("cancellation", "blocked", "Cancellation acknowledgement is required")
    values = (acknowledgement_seconds, cpu_seconds, accelerator_seconds)
    if not all(_finite_number(value) for value in values) or min(values) < 0:
        return _result("cancellation", "fail", "Cancellation measurements and thresholds must be finite and non-negative")
    resolved_device = device.strip().casefold().split(":", maxsplit=1)[0]
    if resolved_device == "cpu":
        threshold = cpu_seconds
    elif resolved_device in {
        "accelerator",
        "cuda",
        "directml",
        "gpu",
        "mps",
        "rocm",
        "xpu",
    }:
        threshold = accelerator_seconds
    else:
        return _result("cancellation", "blocked", "Resolved device is unavailable")
    status: CheckStatus = "pass" if acknowledgement_seconds <= threshold else "fail"
    return _result(
        "cancellation",
        status,
        "Cancellation was acknowledged in time" if status == "pass" else "Cancellation acknowledgement was too slow",
        acknowledgement_seconds=acknowledgement_seconds,
        threshold_seconds=threshold,
        device=device,
    )


def judge_recovery(sample: RecoverySample | None) -> CheckResult:
    if sample is None:
        return _result("recovery", "blocked", "Recovery evidence is required")
    if not sample.interrupted:
        return _result("recovery", "not_applicable", "Workflow was not interrupted")
    if not sample.task_status.strip():
        return _result("recovery", "blocked", "Reconciled task status is required")
    reconciled = sample.task_status.strip().casefold() != "running"
    route_present = not sample.resumable or bool(sample.recovery_route)
    route_matches = (
        not sample.resumable
        or sample.expected_recovery_route is None
        or sample.recovery_route == sample.expected_recovery_route
    )
    status: CheckStatus = "pass" if reconciled and route_present and route_matches else "fail"
    return _result(
        "recovery",
        status,
        "Interrupted workflow is reconciled and recoverable" if status == "pass" else "Interrupted workflow recovery evidence is invalid",
    )


def validate_case(
    case: ParityCase,
    assets: Mapping[str, Path],
    *,
    probe: MediaProbe,
    measurements: Mapping[str, Any],
) -> CaseResult:
    missing_roles = tuple(role for role in case.fixture_roles if role not in assets)
    if missing_roles:
        checks = tuple(
            _result(
                check_id,
                "blocked",
                f"Required fixture assets are unavailable: {', '.join(missing_roles)}",
            )
            for check_id in case.checks
        )
        return CaseResult(case_id=case.case_id, status="blocked", checks=checks)

    results = tuple(
        _validate_check(
            check_id,
            assets=assets,
            probe=probe,
            measurement=measurements.get(check_id),
            thresholds=case.thresholds,
        )
        for check_id in case.checks
    )
    return CaseResult(
        case_id=case.case_id,
        status=_aggregate_status(results),
        checks=results,
    )


def media_matches(
    actual: MediaInfo,
    expected: MediaExpectation,
    *,
    path: Path | None = None,
) -> tuple[str, ...]:
    mismatches: list[str] = []
    if expected.extension is not None:
        expected_extension = _normalize_extension(expected.extension)
        actual_extension = path.suffix.casefold() if path is not None else None
        if actual_extension != expected_extension:
            mismatches.append(
                f"extension: expected {expected_extension!r}, got {actual_extension!r}"
            )
    for name in (
        "container",
        "audio_codec",
        "video_codec",
        "audio_streams",
        "video_streams",
        "subtitle_streams",
        "channels",
        "sample_rate",
    ):
        expected_value = getattr(expected, name)
        actual_value = getattr(actual, name)
        matches = actual_value == expected_value
        if name == "container" and isinstance(actual_value, str):
            matches = str(expected_value).casefold() in {
                item.strip().casefold() for item in actual_value.split(",")
            }
        if expected_value is not None and not matches:
            mismatches.append(f"{name}: expected {expected_value!r}, got {actual_value!r}")
    if expected.duration_seconds is not None and actual.duration_seconds != expected.duration_seconds:
        mismatches.append(
            f"duration_seconds: expected {expected.duration_seconds!r}, got {actual.duration_seconds!r}"
        )
    return tuple(mismatches)


def _validate_check(
    check_id: str,
    *,
    assets: Mapping[str, Path],
    probe: MediaProbe,
    measurement: Any,
    thresholds: Mapping[str, Any],
) -> CheckResult:
    if isinstance(measurement, CheckResult):
        return CheckResult(
            check_id=check_id,
            status=measurement.status,
            message=measurement.message,
            measurements=measurement.measurements,
        )
    if check_id in {"output_format", "output_streams"}:
        return _judge_output_format(
            check_id,
            measurement,
            assets=assets,
            probe=probe,
        )
    if measurement is None:
        return _result(check_id, "blocked", "Required measurement is unavailable")
    mapping_checks = {
        "duration",
        "subtitle_order",
        "subtitle_timing",
        "identity_mapping",
        "speaker_mapping",
        "language_mapping",
        "loudness",
        "performance",
        "interaction_responsiveness",
        "cancellation_acknowledgement",
        "task_reconciliation",
        "recovery_route",
    }
    if check_id in mapping_checks and not isinstance(measurement, Mapping):
        return _result(check_id, "blocked", "Measurement must be an object")
    if check_id == "duration":
        return judge_duration(
            measurement.get("native_seconds"),
            measurement.get("reference_seconds"),
            absolute_ms=_tightened_threshold(thresholds, "duration_absolute_ms", DEFAULT_DURATION_ABSOLUTE_MS),
            relative_ratio=_tightened_threshold(thresholds, "duration_relative_ratio", DEFAULT_DURATION_RELATIVE_RATIO),
        )
    if check_id in {"subtitle_order", "subtitle_timing"}:
        return _with_check_id(
            check_id,
            judge_subtitles(
                measurement.get("native"),
                measurement.get("reference"),
                timing_tolerance_ms=thresholds.get(
                    "subtitle_timing_tolerance_ms",
                    0,
                ),
            ),
        )
    if check_id in {"identity_mapping", "speaker_mapping", "language_mapping"}:
        return _with_check_id(
            check_id,
            judge_identity_mapping(
                measurement.get("native"),
                measurement.get("reference"),
            ),
        )
    if check_id == "loudness":
        return judge_loudness(
            measurement.get("measured_lufs"),
            target_lufs=float(thresholds.get("narration_loudness_target_lufs", DEFAULT_LOUDNESS_TARGET_LUFS)),
            tolerance_lu=_tightened_threshold(thresholds, "loudness_tolerance_lu", DEFAULT_LOUDNESS_TOLERANCE_LU),
        )
    if check_id in {"performance", "interaction_responsiveness"}:
        return _with_check_id(
            check_id,
            judge_performance(
                native=measurement.get("native"),
                reference=measurement.get("reference"),
                max_ratio=_tightened_threshold(
                    thresholds,
                    "reference_performance_ratio",
                    DEFAULT_PERFORMANCE_RATIO,
                ),
                max_response_p95_ms=_tightened_threshold(
                    thresholds,
                    "interaction_p95_ms",
                    DEFAULT_RESPONSE_P95_MS,
                ),
            ),
        )
    if check_id == "cancellation_acknowledgement":
        return _with_check_id(
            check_id,
            judge_cancellation(
                measurement.get("acknowledgement_seconds"),
                device=str(measurement.get("device", "")),
                cpu_seconds=_tightened_threshold(
                    thresholds,
                    "cpu_cancellation_seconds",
                    DEFAULT_CPU_CANCELLATION_SECONDS,
                ),
                accelerator_seconds=_tightened_threshold(
                    thresholds,
                    "accelerator_cancellation_seconds",
                    DEFAULT_ACCELERATOR_CANCELLATION_SECONDS,
                ),
            ),
        )
    if check_id in {"task_reconciliation", "recovery_route"}:
        return _with_check_id(check_id, judge_recovery(measurement.get("sample")))
    if isinstance(measurement, bool):
        return _result(check_id, "pass" if measurement else "fail", "Behavioral assertion completed")
    return _result(check_id, "blocked", "No deterministic judge is registered for this evidence")


def _judge_output_format(
    check_id: str,
    measurement: Any,
    *,
    assets: Mapping[str, Path],
    probe: MediaProbe,
) -> CheckResult:
    if not isinstance(measurement, Mapping):
        return _result(check_id, "blocked", "Output format expectation is required")
    role = measurement.get("role")
    expected_payload = measurement.get("expected")
    if not isinstance(role, str) or role not in assets or not isinstance(expected_payload, Mapping):
        return _result(
            check_id,
            "blocked",
            "Output asset and media expectations are required",
        )
    try:
        expected = MediaExpectation(**dict(expected_payload))
        actual = probe.inspect(assets[role])
    except MediaProbeUnavailable as error:
        return _result(check_id, "blocked", str(error))
    except (OSError, TypeError, ValueError) as error:
        return _result(check_id, "fail", f"Media inspection failed: {error}")
    mismatches = media_matches(actual, expected, path=assets[role])
    if mismatches:
        return _result(check_id, "fail", "; ".join(mismatches))
    return _result(check_id, "pass", "Media streams and metadata match")


def _inspect_json(path: Path) -> MediaInfo:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid JSON file: {error}") from error
    return MediaInfo(container="json")


def _inspect_sqlite(path: Path) -> MediaInfo:
    try:
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA schema_version").fetchone()
    except sqlite3.Error as error:
        raise ValueError(f"Invalid SQLite file: {error}") from error
    return MediaInfo(container="sqlite")


def _inspect_text(path: Path) -> MediaInfo:
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"Invalid UTF-8 text file: {error}") from error
    return MediaInfo(container="text")


def _inspect_zip(path: Path) -> MediaInfo:
    try:
        with zipfile.ZipFile(path) as archive:
            corrupt_member = archive.testzip()
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise ValueError(f"Invalid ZIP file: {error}") from error
    if corrupt_member is not None:
        raise ValueError(f"Invalid ZIP member: {corrupt_member}")
    return MediaInfo(container="zip")


def _inspect_wav(path: Path) -> MediaInfo:
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            compression = source.getcomptype()
    except (OSError, EOFError, wave.Error) as error:
        raise ValueError(f"Invalid WAV file: {error}") from error
    if compression != "NONE" or sample_width not in {1, 2, 3, 4}:
        raise ValueError("Unsupported WAV encoding")
    codec = {1: "pcm_u8", 2: "pcm_s16le", 3: "pcm_s24le", 4: "pcm_s32le"}[sample_width]
    return MediaInfo(
        container="wav",
        audio_codec=codec,
        audio_streams=1,
        channels=channels,
        sample_rate=sample_rate,
        duration_seconds=frame_count / sample_rate if sample_rate else None,
    )


def _media_info_from_ffprobe(payload: Any) -> MediaInfo:
    if not isinstance(payload, Mapping):
        raise ValueError("ffprobe payload must be an object")
    raw_streams = payload.get("streams", [])
    if not isinstance(raw_streams, list):
        raise ValueError("ffprobe streams must be an array")
    audio = [stream for stream in raw_streams if isinstance(stream, Mapping) and stream.get("codec_type") == "audio"]
    video = [stream for stream in raw_streams if isinstance(stream, Mapping) and stream.get("codec_type") == "video"]
    subtitles = [stream for stream in raw_streams if isinstance(stream, Mapping) and stream.get("codec_type") == "subtitle"]
    format_payload = payload.get("format", {})
    if not isinstance(format_payload, Mapping):
        raise ValueError("ffprobe format must be an object")
    format_name = str(format_payload.get("format_name", ""))
    duration_value = format_payload.get("duration")
    return MediaInfo(
        container=format_name or "unknown",
        audio_codec=str(audio[0].get("codec_name")) if audio else None,
        video_codec=str(video[0].get("codec_name")) if video else None,
        audio_streams=len(audio),
        video_streams=len(video),
        subtitle_streams=len(subtitles),
        channels=_optional_int(audio[0].get("channels")) if audio else None,
        sample_rate=_optional_int(audio[0].get("sample_rate")) if audio else None,
        duration_seconds=_optional_float(duration_value),
    )


def _subtitle_cue(cue: Any) -> tuple[int, int, str]:
    if isinstance(cue, Mapping):
        start = cue["start_ms"]
        end = cue["end_ms"]
        text = cue["text"]
    else:
        start = getattr(cue, "start_ms")
        end = getattr(cue, "end_ms")
        text = getattr(cue, "text")
    if isinstance(start, bool) or not isinstance(start, int) or isinstance(end, bool) or not isinstance(end, int):
        raise TypeError("cue times must be integer milliseconds")
    if start < 0 or end < start or not isinstance(text, str):
        raise ValueError("cue timing or text is invalid")
    return start, end, " ".join(text.split())


def _normalize_identity_mapping(mapping: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in mapping.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("identity keys and values must be strings")
        normalized_key = _normalize_id(key)
        normalized_value = _normalize_id(value)
        if not normalized_key or not normalized_value:
            raise ValueError("identity IDs cannot be empty")
        if normalized_key in normalized:
            raise ValueError("identity keys collide after normalization")
        normalized[normalized_key] = normalized_value
    return normalized


def _normalize_id(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _normalize_extension(value: str) -> str:
    normalized = value.strip().casefold()
    return normalized if normalized.startswith(".") else f".{normalized}"


def _aggregate_status(results: Sequence[CheckResult]) -> CheckStatus:
    statuses = {result.status for result in results}
    for status in ("fail", "blocked", "manual_pending", "pass"):
        if status in statuses:
            return status  # type: ignore[return-value]
    return "not_applicable"


def _tightened_threshold(thresholds: Mapping[str, Any], name: str, default: float) -> float:
    value = float(thresholds.get(name, default))
    return min(value, default)


def _percentile_95(samples: Sequence[float]) -> float:
    ordered = sorted(samples)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid integer media field: {value!r}") from error


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid numeric media field: {value!r}") from error
    if not math.isfinite(result):
        raise ValueError(f"Invalid numeric media field: {value!r}")
    return result


def _result(
    check_id: str,
    status: CheckStatus,
    message: str,
    **measurements: object,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        status=status,
        message=message,
        measurements=measurements,
    )


def _with_check_id(check_id: str, result: CheckResult) -> CheckResult:
    if result.check_id == check_id:
        return result
    return CheckResult(
        check_id=check_id,
        status=result.status,
        message=result.message,
        measurements=result.measurements,
    )
