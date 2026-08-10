from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from ..longform import PAUSE_SPAN, SPEECH_SPAN, LongformSpan, parse_audiobook_script


@dataclass(frozen=True)
class AudiobookOverrides:
    speed: float = 1.0
    pause_after_ms: int = 500


@dataclass(frozen=True)
class AudiobookSpan:
    kind: str
    text: str
    voice_name: str
    profile_id: str
    speed: float
    pause_ms: int = 0


@dataclass(frozen=True)
class AudiobookChapterPlan:
    title: str
    spans: tuple[AudiobookSpan, ...]
    speed: float
    pause_after_ms: int


@dataclass(frozen=True)
class AudiobookIssue:
    code: str
    message: str
    chapter: str = ""
    severity: str = "warning"


@dataclass(frozen=True)
class AudiobookStats:
    chapter_count: int
    span_count: int
    word_count: int
    estimated_seconds: float


@dataclass(frozen=True)
class AudiobookPlan:
    chapters: tuple[AudiobookChapterPlan, ...]
    warnings: tuple[AudiobookIssue, ...]
    errors: tuple[AudiobookIssue, ...]
    stats: AudiobookStats

    def to_longform_plan(self):
        from ..longform import LongformPlan

        spans: list[LongformSpan] = []
        for chapter in self.chapters:
            for span in chapter.spans:
                if span.kind == PAUSE_SPAN:
                    spans.append(
                        LongformSpan(
                            kind=PAUSE_SPAN,
                            pause_ms=span.pause_ms,
                            chapter=chapter.title,
                        )
                    )
                else:
                    spans.append(
                        LongformSpan(
                            kind=SPEECH_SPAN,
                            text=span.text,
                            voice_name=span.voice_name,
                            profile_id=span.profile_id,
                            speed=span.speed,
                            chapter=chapter.title,
                        )
                    )
            if chapter.pause_after_ms > 0:
                spans.append(
                    LongformSpan(
                        kind=PAUSE_SPAN,
                        pause_ms=chapter.pause_after_ms,
                        chapter=chapter.title,
                    )
                )
        return LongformPlan(
            spans=tuple(spans),
            chapters=tuple(chapter.title for chapter in self.chapters),
        )


def build_audiobook_plan(
    source: str,
    *,
    cast: Mapping[str, str],
    lexicon: Mapping[str, str],
    overrides: Mapping[str, AudiobookOverrides] | None = None,
    max_span_chars: int = 500,
) -> AudiobookPlan:
    parsed = parse_audiobook_script(source)
    chapter_spans: dict[str, list[AudiobookSpan]] = {title: [] for title in parsed.chapters}
    warnings: list[AudiobookIssue] = []
    errors: list[AudiobookIssue] = []
    words = 0
    speech_count = 0
    seen_unassigned: set[tuple[str, str]] = set()
    override_map = overrides or {}
    for span in parsed.spans:
        chapter = span.chapter or (parsed.chapters[0] if parsed.chapters else "Nội dung")
        chapter_spans.setdefault(chapter, [])
        chapter_override = override_map.get(chapter, AudiobookOverrides())
        if span.kind == PAUSE_SPAN:
            chapter_spans[chapter].append(
                AudiobookSpan(PAUSE_SPAN, "", span.voice_name, "", 1.0, span.pause_ms)
            )
            continue
        text = _apply_lexicon(span.text, lexicon)
        profile_id = cast.get(span.voice_name, "") if span.voice_name else ""
        if span.voice_name and not profile_id and (chapter, span.voice_name) not in seen_unassigned:
            warnings.append(
                AudiobookIssue(
                    "unassigned-voice",
                    f"Vai '{span.voice_name}' chưa được gán profile.",
                    chapter,
                )
            )
            seen_unassigned.add((chapter, span.voice_name))
        if len(text) > max(40, int(max_span_chars)):
            warnings.append(
                AudiobookIssue(
                    "long-span",
                    f"Đoạn dài {len(text)} ký tự; nên tách để render ổn định.",
                    chapter,
                )
            )
        speed = max(0.5, min(1.5, span.speed * chapter_override.speed))
        chapter_spans[chapter].append(
            AudiobookSpan(SPEECH_SPAN, text, span.voice_name, profile_id, speed)
        )
        words += len(re.findall(r"\S+", text))
        speech_count += 1
    chapters = tuple(
        AudiobookChapterPlan(
            title=title,
            spans=tuple(chapter_spans.get(title, ())),
            speed=max(0.5, min(1.5, override_map.get(title, AudiobookOverrides()).speed)),
            pause_after_ms=max(
                0,
                min(10_000, override_map.get(title, AudiobookOverrides()).pause_after_ms),
            ),
        )
        for title in parsed.chapters
    )
    if not chapters:
        errors.append(AudiobookIssue("no-chapters", "Không tìm thấy chương.", severity="error"))
    if speech_count == 0:
        errors.append(AudiobookIssue("no-speech", "Không có nội dung để đọc.", severity="error"))
    average_wpm = 150.0
    estimated_seconds = words / average_wpm * 60.0
    return AudiobookPlan(
        chapters=chapters,
        warnings=tuple(warnings),
        errors=tuple(errors),
        stats=AudiobookStats(len(chapters), speech_count, words, estimated_seconds),
    )


def _apply_lexicon(text: str, lexicon: Mapping[str, str]) -> str:
    result = text
    for source, replacement in sorted(lexicon.items(), key=lambda item: len(item[0]), reverse=True):
        if not source.strip() or not replacement.strip():
            continue
        result = re.sub(re.escape(source.strip()), replacement.strip(), result, flags=re.IGNORECASE)
    return result
