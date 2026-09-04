from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import OcrBox, OcrCue, OcrObservation

_SPACE_PATTERN = re.compile(r"\s+")


def normalized_ocr_text(value: str) -> str:
    return _SPACE_PATTERN.sub(" ", value).strip().casefold()


def text_similarity(first: str, second: str) -> float:
    left = normalized_ocr_text(first)
    right = normalized_ocr_text(second)
    if not left or not right:
        return float(left == right)
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def vote_observations(
    observations: tuple[OcrObservation, ...],
    *,
    similarity_threshold: float = 0.84,
) -> OcrObservation:
    readable = [item for item in observations if normalized_ocr_text(item.text)]
    if not readable:
        timestamp = min((item.timestamp_ms for item in observations), default=0)
        return OcrObservation(timestamp, "", 0.0)

    clusters: list[list[OcrObservation]] = []
    for observation in readable:
        cluster = next(
            (
                candidate
                for candidate in clusters
                if text_similarity(candidate[0].text, observation.text) >= similarity_threshold
            ),
            None,
        )
        if cluster is None:
            clusters.append([observation])
        else:
            cluster.append(observation)

    winner = max(
        clusters,
        key=lambda cluster: (
            len(cluster),
            sum(item.confidence for item in cluster) / len(cluster),
            max(len(item.text.strip()) for item in cluster),
        ),
    )
    best = max(winner, key=lambda item: (item.confidence, len(item.text.strip())))
    return OcrObservation(
        timestamp_ms=min(item.timestamp_ms for item in winner),
        text=best.text.strip(),
        confidence=sum(item.confidence for item in winner) / len(winner),
        boxes=_merge_boxes(winner),
    )


def merge_observations(
    observations: list[OcrObservation],
    *,
    sample_interval_ms: int,
    duration_ms: int,
    similarity_threshold: float = 0.84,
) -> tuple[OcrCue, ...]:
    if sample_interval_ms < 1:
        raise ValueError("sample_interval_ms must be positive")
    if duration_ms < 1:
        raise ValueError("duration_ms must be positive")

    ordered = sorted(observations, key=lambda item: item.timestamp_ms)
    groups: list[list[OcrObservation]] = []
    active: list[OcrObservation] = []
    maximum_gap = max(sample_interval_ms * 2, 700)

    for observation in ordered:
        if not normalized_ocr_text(observation.text):
            if active:
                groups.append(active)
                active = []
            continue
        if active:
            previous = active[-1]
            same_caption = (
                observation.timestamp_ms - previous.timestamp_ms <= maximum_gap
                and text_similarity(previous.text, observation.text) >= similarity_threshold
            )
            if not same_caption:
                groups.append(active)
                active = []
        active.append(observation)
    if active:
        groups.append(active)

    cues: list[OcrCue] = []
    padding = max(1, sample_interval_ms // 2)
    for group in groups:
        best = max(group, key=lambda item: (item.confidence, len(item.text.strip())))
        start_ms = max(0, group[0].timestamp_ms - padding)
        end_ms = min(duration_ms, group[-1].timestamp_ms + sample_interval_ms)
        if end_ms <= start_ms:
            end_ms = min(duration_ms, start_ms + max(1, sample_interval_ms))
        cues.append(
            OcrCue(
                index=len(cues) + 1,
                start_ms=start_ms,
                end_ms=max(start_ms + 1, end_ms),
                text=best.text.strip(),
                confidence=sum(item.confidence for item in group) / len(group),
                boxes=_merge_boxes(group),
            )
        )
    return tuple(cues)


def drop_static_cues(
    cues: tuple[OcrCue, ...],
    *,
    duration_ms: int,
    minimum_duration_ms: int = 10_000,
    coverage_threshold: float = 0.9,
) -> tuple[tuple[OcrCue, ...], tuple[OcrCue, ...]]:
    if duration_ms < 1:
        raise ValueError("duration_ms must be positive")
    kept: list[OcrCue] = []
    static: list[OcrCue] = []
    for cue in cues:
        cue_duration = max(0, cue.end_ms - cue.start_ms)
        is_static = (
            cue_duration >= minimum_duration_ms
            and cue_duration / duration_ms >= coverage_threshold
            and len(normalized_ocr_text(cue.text)) <= 48
        )
        (static if is_static else kept).append(cue)
    return tuple(kept), tuple(static)


def _merge_boxes(observations: list[OcrObservation]) -> tuple[OcrBox, ...]:
    boxes = [box for observation in observations for box in observation.boxes]
    if not boxes:
        return ()
    left = min(box.x for box in boxes)
    top = min(box.y for box in boxes)
    right = max(box.x + box.width for box in boxes)
    bottom = max(box.y + box.height for box in boxes)
    return (OcrBox(left, top, right - left, bottom - top),)
