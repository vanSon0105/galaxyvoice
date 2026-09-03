from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, Sequence, TypeVar

from ..voice.text_splitter import normalize_text


class ShortCue(Protocol):
    item_id: str
    track_id: str
    start_ms: int
    end_ms: int
    text: str
    language: str


CueT = TypeVar("CueT", bound=ShortCue)


@dataclass(frozen=True)
class ShortCueLimits:
    short_cue_chars: int = 56
    max_cluster_chars: int = 220
    max_cluster_cues: int = 4
    max_cluster_span_ms: int = 12_000
    max_join_gap_ms: int = 750


@dataclass(frozen=True)
class SpeechCueGroup(Generic[CueT]):
    cues: tuple[CueT, ...]

    @property
    def clustered(self) -> bool:
        return len(self.cues) > 1


def plan_short_cues(
    cues: Sequence[CueT],
    limits: ShortCueLimits | None = None,
) -> tuple[SpeechCueGroup[CueT], ...]:
    active_limits = limits or ShortCueLimits()
    groups: list[SpeechCueGroup[CueT]] = []
    current: list[CueT] = []

    def flush() -> None:
        if current:
            groups.append(SpeechCueGroup(tuple(current)))
            current.clear()

    for cue in cues:
        if _text_length(cue) > active_limits.short_cue_chars:
            flush()
            groups.append(SpeechCueGroup((cue,)))
            continue
        if current and not _can_join(current, cue, active_limits):
            flush()
        current.append(cue)
    flush()
    return tuple(groups)


def cue_end_ms(cue: ShortCue) -> int:
    return cue.end_ms if cue.end_ms > cue.start_ms else cue.start_ms + 1


def _can_join(current: list[CueT], cue: CueT, limits: ShortCueLimits) -> bool:
    first = current[0]
    previous = current[-1]
    gap_ms = cue.start_ms - cue_end_ms(previous)
    cluster_chars = sum(_text_length(item) for item in current) + len(current) + _text_length(cue)
    return (
        cue.track_id == previous.track_id
        and cue.language == previous.language
        and 0 <= gap_ms <= limits.max_join_gap_ms
        and len(current) < limits.max_cluster_cues
        and cluster_chars <= limits.max_cluster_chars
        and cue_end_ms(cue) - first.start_ms <= limits.max_cluster_span_ms
    )


def _text_length(cue: ShortCue) -> int:
    return len(normalize_text(cue.text))
