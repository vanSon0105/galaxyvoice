from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ..voice.srt import SubtitleCue


VIDEO_ASSET = "video"
AUDIO_ASSET = "audio"
SUBTITLE_ASSET = "subtitle"
EDITOR_ASSET_KINDS = (VIDEO_ASSET, AUDIO_ASSET, SUBTITLE_ASSET)


@dataclass(frozen=True)
class EditorAsset:
    asset_id: str
    kind: str
    path: str
    duration_seconds: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    cues: tuple[SubtitleCue, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in EDITOR_ASSET_KINDS:
            raise ValueError(f"Unsupported editor asset kind: {self.kind}")

    @property
    def name(self) -> str:
        return Path(self.path).name


def normalize_cues(cues: list[SubtitleCue], duration_ms: int | None = None) -> list[SubtitleCue]:
    """Sort, clamp, and reindex subtitle cues for the editor timeline."""
    normalized: list[SubtitleCue] = []
    maximum = max(1, int(duration_ms)) if duration_ms is not None else None
    for cue in sorted(cues, key=lambda item: (item.start_ms, item.end_ms, item.index)):
        start_ms = max(0, int(cue.start_ms))
        end_ms = max(start_ms + 1, int(cue.end_ms))
        if maximum is not None:
            if start_ms >= maximum:
                continue
            end_ms = min(maximum, end_ms)
        text = cue.text.strip()
        if text:
            normalized.append(
                SubtitleCue(
                    index=len(normalized) + 1,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                )
            )
    return normalized


def fit_cues_to_duration(cues: list[SubtitleCue], duration_ms: int) -> list[SubtitleCue]:
    """Scale a subtitle track so its first cue starts at zero and its last cue ends with the video."""
    normalized = normalize_cues(cues)
    if not normalized or duration_ms <= 0:
        return normalized
    first_ms = normalized[0].start_ms
    span_ms = max(1, max(cue.end_ms for cue in normalized) - first_ms)
    scale = duration_ms / span_ms
    fitted = [
        replace(
            cue,
            start_ms=max(0, round((cue.start_ms - first_ms) * scale)),
            end_ms=min(duration_ms, max(1, round((cue.end_ms - first_ms) * scale))),
        )
        for cue in normalized
    ]
    return normalize_cues(fitted, duration_ms)


def update_cue(
    cues: list[SubtitleCue],
    cue_index: int,
    *,
    start_ms: int,
    end_ms: int,
    text: str,
    duration_ms: int | None = None,
) -> list[SubtitleCue]:
    if cue_index < 0 or cue_index >= len(cues):
        raise IndexError("Subtitle cue does not exist.")
    if end_ms <= start_ms:
        raise ValueError("Subtitle end time must be after its start time.")
    if not text.strip():
        raise ValueError("Subtitle text cannot be empty.")
    updated = list(cues)
    updated[cue_index] = SubtitleCue(
        index=cue_index + 1,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text.strip(),
    )
    return normalize_cues(updated, duration_ms)


def parse_timecode(value: str) -> int:
    """Parse seconds, MM:SS.mmm, or HH:MM:SS,mmm into milliseconds."""
    cleaned = value.strip().replace(",", ".")
    if not cleaned:
        raise ValueError("Timecode is empty.")
    parts = cleaned.split(":")
    if len(parts) > 3:
        raise ValueError(f"Invalid timecode: {value}")
    try:
        seconds = float(parts[-1])
        minutes = int(parts[-2]) if len(parts) >= 2 else 0
        hours = int(parts[-3]) if len(parts) == 3 else 0
    except ValueError as error:
        raise ValueError(f"Invalid timecode: {value}") from error
    if hours < 0 or minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60:
        if len(parts) == 1 and seconds >= 0:
            return round(seconds * 1000)
        raise ValueError(f"Invalid timecode: {value}")
    return round((hours * 3600 + minutes * 60 + seconds) * 1000)


def format_timecode(milliseconds: int) -> str:
    total_ms = max(0, int(milliseconds))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"
    return f"{minutes:02}:{seconds:02}.{millis:03}"
