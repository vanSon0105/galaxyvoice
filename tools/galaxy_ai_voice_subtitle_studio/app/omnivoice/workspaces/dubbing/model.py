from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from typing import Iterable
from uuid import uuid4

from ....common.cache import stable_digest
from ....voice.srt import SubtitleCue
from ..longform import LongformPlan, LongformSpan, PAUSE_SPAN, SPEECH_SPAN


_SPEAKER_TAG = re.compile(r"^\s*\[speaker:([^\]]+)\]\s*(.*)$", re.IGNORECASE | re.DOTALL)
_SPEAKER_PREFIX = re.compile(r"^\s*([^:\n]{1,40}):\s+(.+)$", re.DOTALL)
_SENTENCE_BREAK = re.compile(r"[.!?。！？](?:\s+|$)")


@dataclass(frozen=True)
class DubbingSegment:
    segment_id: str
    start_ms: int
    end_ms: int
    source_text: str
    text: str
    speaker_id: str = "Default"
    profile_id: str = ""
    speed: float = 1.0
    volume: float = 1.0
    preview_path: str = ""
    source_speaker_id: str = ""

    @property
    def duration_ms(self) -> int:
        return max(1, self.end_ms - self.start_ms)


@dataclass(frozen=True)
class DubbingIssue:
    code: str
    segment_id: str
    message: str
    severity: str = "warning"


@dataclass(frozen=True)
class DubbingFitPolicy:
    """Quality limits for pitch-preserving duration fitting."""

    min_tempo: float = 0.80
    max_tempo: float = 1.25
    tolerance_ms: int = 120
    min_gap_ms: int = 80
    max_chars_per_second: float = 22.0


@dataclass(frozen=True)
class DubbingSegmentMeasurement:
    segment_id: str
    raw_duration_ms: int
    tempo: float
    tempo_duration_ms: int
    fitted_duration_ms: int
    method: str
    clipped_ms: int = 0
    padded_ms: int = 0


@dataclass(frozen=True)
class DubbingQualityReport:
    report_id: str
    score: int
    segment_count: int
    error_count: int
    warning_count: int
    issues: tuple[DubbingIssue, ...]
    measurements: tuple[DubbingSegmentMeasurement, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "score": self.score,
            "segment_count": self.segment_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [asdict(issue) for issue in self.issues],
            "measurements": [asdict(item) for item in self.measurements],
        }


def build_dubbing_segments(
    source_cues: list[SubtitleCue] | tuple[SubtitleCue, ...],
    translated_cues: list[SubtitleCue] | tuple[SubtitleCue, ...] | None = None,
) -> tuple[DubbingSegment, ...]:
    translations = {cue.index: cue for cue in translated_cues or ()}
    segments: list[DubbingSegment] = []
    for cue in source_cues:
        source_speaker, source_text = _extract_speaker(cue.text)
        translated = translations.get(cue.index)
        translated_speaker, translated_text = _extract_speaker(
            translated.text if translated else source_text
        )
        segments.append(
            DubbingSegment(
                segment_id=f"seg-{cue.index}",
                start_ms=max(0, int(cue.start_ms)),
                end_ms=max(int(cue.start_ms) + 1, int(cue.end_ms)),
                source_text=source_text,
                text=translated_text,
                speaker_id=source_speaker or translated_speaker or "Default",
            )
        )
    return tuple(segments)


def split_dubbing_segment(
    segment: DubbingSegment,
    split_index: int | None = None,
) -> tuple[DubbingSegment, DubbingSegment]:
    text = segment.text.strip()
    if len(text) < 2:
        raise ValueError("Segment quá ngắn để tách.")
    index = split_index if split_index is not None else _best_split_index(text)
    index = max(1, min(len(text) - 1, int(index)))
    left_text = text[:index].strip()
    right_text = text[index:].strip()
    if not left_text or not right_text:
        raise ValueError("Điểm tách phải nằm giữa hai phần có nội dung.")
    ratio = len(left_text) / max(1, len(left_text) + len(right_text))
    split_ms = segment.start_ms + round(segment.duration_ms * ratio)
    split_ms = max(segment.start_ms + 1, min(segment.end_ms - 1, split_ms))
    return (
        replace(segment, end_ms=split_ms, text=left_text, preview_path=""),
        replace(
            segment,
            segment_id=f"seg-{uuid4().hex[:10]}",
            start_ms=split_ms,
            text=right_text,
            preview_path="",
        ),
    )


def merge_dubbing_segments(
    first: DubbingSegment,
    second: DubbingSegment,
) -> DubbingSegment:
    if second.start_ms < first.start_ms:
        first, second = second, first
    return replace(
        first,
        end_ms=max(first.end_ms, second.end_ms),
        source_text=" ".join(part for part in (first.source_text, second.source_text) if part),
        text=" ".join(part for part in (first.text, second.text) if part),
        preview_path="",
    )


def plan_dubbing_segments(segments: tuple[DubbingSegment, ...]) -> LongformPlan:
    ordered = tuple(sorted(segments, key=lambda item: (item.start_ms, item.end_ms)))
    if not ordered:
        raise ValueError("Không có segment để lồng tiếng.")
    spans: list[LongformSpan] = []
    cursor = 0
    for index, segment in enumerate(ordered, start=1):
        if segment.start_ms > cursor:
            spans.append(LongformSpan(kind=PAUSE_SPAN, pause_ms=segment.start_ms - cursor))
        spans.append(
            LongformSpan(
                kind=SPEECH_SPAN,
                text=segment.text.strip(),
                voice_name=segment.speaker_id,
                profile_id=segment.profile_id,
                speed=max(0.5, min(1.5, segment.speed)),
                volume=max(0.0, min(2.0, segment.volume)),
                duration=segment.duration_ms / 1000,
                chapter="Video Dubbing",
                source_index=index,
                segment_id=segment.segment_id,
            )
        )
        cursor = max(cursor, segment.end_ms)
    return LongformPlan(spans=tuple(spans), chapters=("Video Dubbing",))


def validate_dubbing_segments(
    segments: tuple[DubbingSegment, ...],
    *,
    max_chars_per_second: float = 22.0,
) -> tuple[DubbingIssue, ...]:
    issues: list[DubbingIssue] = []
    ordered = tuple(sorted(segments, key=lambda item: (item.start_ms, item.end_ms)))
    seen_ids: set[str] = set()
    previous: DubbingSegment | None = None
    for segment in ordered:
        if not segment.segment_id.strip():
            issues.append(DubbingIssue("missing-id", "", "Segment chưa có mã định danh.", "error"))
        elif segment.segment_id in seen_ids:
            issues.append(
                DubbingIssue(
                    "duplicate-id",
                    segment.segment_id,
                    "Mã segment bị trùng; checkpoint và preview sẽ không ổn định.",
                    "error",
                )
            )
        seen_ids.add(segment.segment_id)
        if segment.end_ms <= segment.start_ms:
            issues.append(
                DubbingIssue(
                    "invalid-timing",
                    segment.segment_id,
                    "Thời điểm kết thúc phải lớn hơn thời điểm bắt đầu.",
                    "error",
                )
            )
        if not segment.text.strip():
            issues.append(DubbingIssue("empty", segment.segment_id, "Segment chưa có lời dịch.", "error"))
        if previous is not None and segment.start_ms < previous.end_ms:
            issues.append(DubbingIssue("overlap", segment.segment_id, "Segment chồng thời gian với câu trước.", "error"))
        pressure = len(segment.text.strip()) / max(0.001, segment.duration_ms / 1000)
        if segment.text.strip() and pressure > max_chars_per_second:
            issues.append(
                DubbingIssue(
                    "reading-pressure",
                    segment.segment_id,
                    f"Lời dịch quá dài cho {segment.duration_ms / 1000:.2f} giây.",
                )
            )
        previous = segment
    return tuple(issues)


def build_dubbing_quality_report(
    segments: Iterable[DubbingSegment],
    *,
    measurements: Iterable[DubbingSegmentMeasurement] = (),
    policy: DubbingFitPolicy | None = None,
) -> DubbingQualityReport:
    """Build a deterministic preflight or post-render quality report."""

    resolved_policy = policy or DubbingFitPolicy()
    ordered = tuple(sorted(segments, key=lambda item: (item.start_ms, item.end_ms)))
    measured = tuple(measurements)
    measured_by_id = {item.segment_id: item for item in measured}
    issues = list(
        validate_dubbing_segments(
            ordered,
            max_chars_per_second=resolved_policy.max_chars_per_second,
        )
    )
    previous: DubbingSegment | None = None
    for segment in ordered:
        if previous is not None:
            gap_ms = segment.start_ms - previous.end_ms
            if 0 <= gap_ms < resolved_policy.min_gap_ms:
                issues.append(
                    DubbingIssue(
                        "tight-gap",
                        segment.segment_id,
                        f"Khoảng nghỉ {gap_ms} ms quá ngắn; dễ nghe dính vào câu trước.",
                    )
                )
        if not segment.profile_id.strip():
            issues.append(
                DubbingIssue(
                    "unmapped-speaker",
                    segment.segment_id,
                    f"Người nói {segment.speaker_id or 'Default'} chưa được gán voice.",
                )
            )
        measurement = measured_by_id.get(segment.segment_id)
        if measurement is not None:
            if measurement.clipped_ms > resolved_policy.tolerance_ms:
                issues.append(
                    DubbingIssue(
                        "fit-limit",
                        segment.segment_id,
                        f"Voice vượt khung {measurement.clipped_ms} ms sau khi đã chạm giới hạn Smart Fit.",
                        "error",
                    )
                )
            elif measurement.padded_ms > max(resolved_policy.tolerance_ms, segment.duration_ms // 3):
                issues.append(
                    DubbingIssue(
                        "underfill",
                        segment.segment_id,
                        f"Voice ngắn hơn khung {measurement.padded_ms} ms; nên nghe lại nhịp câu.",
                    )
                )
        previous = segment

    errors = sum(issue.severity == "error" for issue in issues)
    warnings = len(issues) - errors
    score = max(0, 100 - errors * 20 - warnings * 5)
    identity = {
        "segments": [asdict(segment) for segment in ordered],
        "measurements": [asdict(item) for item in measured],
        "policy": asdict(resolved_policy),
    }
    return DubbingQualityReport(
        report_id=stable_digest(identity)[:16],
        score=score,
        segment_count=len(ordered),
        error_count=errors,
        warning_count=warnings,
        issues=tuple(issues),
        measurements=measured,
    )


def _extract_speaker(text: str) -> tuple[str, str]:
    cleaned = text.strip()
    tagged = _SPEAKER_TAG.match(cleaned)
    if tagged:
        return tagged.group(1).strip(), tagged.group(2).strip()
    prefixed = _SPEAKER_PREFIX.match(cleaned)
    if prefixed:
        return prefixed.group(1).strip(), prefixed.group(2).strip()
    return "", cleaned


def _best_split_index(text: str) -> int:
    candidates = [match.end() for match in _SENTENCE_BREAK.finditer(text)]
    midpoint = len(text) // 2
    if candidates:
        return min(candidates, key=lambda value: abs(value - midpoint))
    spaces = [index for index, character in enumerate(text) if character.isspace()]
    return min(spaces, key=lambda value: abs(value - midpoint)) if spaces else midpoint
