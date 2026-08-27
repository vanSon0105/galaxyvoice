from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ...voice.srt import SubtitleCue
from .expressive import (
    PAUSE_DIRECTIVE,
    ExpressiveIssue,
    PronunciationRule,
    compile_expressive_text,
)


SPEECH_SPAN = "speech"
PAUSE_SPAN = "pause"
_HEADING_RE = re.compile(r"^\s*#\s+(.+?)\s*$")
_CHARACTER_RE = re.compile(r"^\s*([^:\[\]\n]{1,48}):\s+(.+)$")
_VOICE_RE = re.compile(r"\[voice:([^\[\]]*)\]", re.IGNORECASE)


@dataclass(frozen=True)
class LongformSpan:
    kind: str
    text: str = ""
    voice_name: str = ""
    profile_id: str = ""
    pause_ms: int = 0
    speed: float = 1.0
    volume: float = 1.0
    duration: float | None = None
    chapter: str = ""
    source_index: int | None = None
    segment_id: str = ""
    display_text: str = ""
    instruction: str = ""
    emotion: str = ""
    emphasis: bool = False
    spell: bool = False


@dataclass(frozen=True)
class LongformPlan:
    spans: tuple[LongformSpan, ...]
    chapters: tuple[str, ...]
    issues: tuple[ExpressiveIssue, ...] = ()

    @property
    def voice_names(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(span.voice_name for span in self.spans if span.voice_name)
        )


def parse_story_script(
    source: str,
    *,
    language: str = "auto",
    pronunciation_rules: Iterable[PronunciationRule] = (),
) -> LongformPlan:
    return _parse_script(
        source,
        character_prefixes=True,
        default_chapter="Câu chuyện",
        language=language,
        pronunciation_rules=tuple(pronunciation_rules),
    )


def parse_audiobook_script(
    source: str,
    *,
    language: str = "auto",
    pronunciation_rules: Iterable[PronunciationRule] = (),
) -> LongformPlan:
    return _parse_script(
        source,
        character_prefixes=False,
        default_chapter="Nội dung",
        language=language,
        pronunciation_rules=tuple(pronunciation_rules),
    )


def detect_longform_workspace_kind(source: str) -> str:
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    if any(_CHARACTER_RE.fullmatch(line) for line in lines):
        return "stories"
    chapter_count = sum(1 for line in lines if _HEADING_RE.fullmatch(line))
    has_voice_markup = any("[voice:" in line.casefold() for line in lines)
    return "audiobook" if chapter_count >= 2 or has_voice_markup else "stories"


def plan_dubbing_cues(cues: list[SubtitleCue]) -> LongformPlan:
    if not cues:
        raise ValueError("Không có cue phụ đề để tạo bản lồng tiếng.")
    spans: list[LongformSpan] = []
    cursor_ms = 0
    for cue in cues:
        start_ms = max(cursor_ms, int(cue.start_ms))
        if start_ms > cursor_ms:
            spans.append(LongformSpan(kind=PAUSE_SPAN, pause_ms=start_ms - cursor_ms))
        end_ms = max(start_ms + 1, int(cue.end_ms))
        spans.append(
            LongformSpan(
                kind=SPEECH_SPAN,
                text=cue.text.strip(),
                duration=(end_ms - start_ms) / 1000.0,
                chapter="Video Dubbing",
                source_index=cue.index,
            )
        )
        cursor_ms = end_ms
    return LongformPlan(spans=tuple(spans), chapters=("Video Dubbing",))


def _parse_script(
    source: str,
    *,
    character_prefixes: bool,
    default_chapter: str,
    language: str,
    pronunciation_rules: tuple[PronunciationRule, ...],
) -> LongformPlan:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("Nội dung không được để trống.")
    spans: list[LongformSpan] = []
    chapters: list[str] = []
    issues: list[ExpressiveIssue] = []
    chapter = default_chapter
    voice = ""
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = _HEADING_RE.fullmatch(line)
        if heading:
            chapter = heading.group(1).strip()
            if chapter and chapter not in chapters:
                chapters.append(chapter)
            continue
        if chapter not in chapters:
            chapters.append(chapter)
        if character_prefixes:
            character = _CHARACTER_RE.fullmatch(line)
            if character:
                voice = character.group(1).strip()
                line = character.group(2).strip()
        line_spans, voice, line_issues = _parse_markup(
            line,
            voice=voice,
            chapter=chapter,
            language=language,
            pronunciation_rules=pronunciation_rules,
        )
        spans.extend(line_spans)
        issues.extend(line_issues)
    if not any(span.kind == SPEECH_SPAN for span in spans):
        raise ValueError("Nội dung không có đoạn thoại nào để tạo giọng.")
    return LongformPlan(spans=tuple(spans), chapters=tuple(chapters), issues=tuple(issues))


def _parse_markup(
    text: str,
    *,
    voice: str,
    chapter: str,
    language: str,
    pronunciation_rules: tuple[PronunciationRule, ...],
) -> tuple[list[LongformSpan], str, list[ExpressiveIssue]]:
    spans: list[LongformSpan] = []
    issues: list[ExpressiveIssue] = []
    cursor = 0
    for match in _VOICE_RE.finditer(text):
        if match.start() > cursor:
            _append_compiled(
                spans,
                issues,
                text[cursor:match.start()],
                voice=voice,
                chapter=chapter,
                language=language,
                pronunciation_rules=pronunciation_rules,
            )
        selected = match.group(1).strip()
        voice = "" if selected.casefold() in {"", "default"} else selected
        cursor = match.end()
    if cursor < len(text):
        _append_compiled(
            spans,
            issues,
            text[cursor:],
            voice=voice,
            chapter=chapter,
            language=language,
            pronunciation_rules=pronunciation_rules,
        )
    return spans, voice, issues


def _append_compiled(
    spans: list[LongformSpan],
    issues: list[ExpressiveIssue],
    text: str,
    *,
    voice: str,
    chapter: str,
    language: str,
    pronunciation_rules: tuple[PronunciationRule, ...],
) -> None:
    compiled = compile_expressive_text(
        text,
        language=language,
        pronunciation_rules=pronunciation_rules,
    )
    issues.extend(compiled.issues)
    for directive in compiled.directives:
        if directive.kind == PAUSE_DIRECTIVE:
            spans.append(
                LongformSpan(kind=PAUSE_SPAN, pause_ms=directive.pause_ms, chapter=chapter)
            )
            continue
        spans.append(
            LongformSpan(
                kind=SPEECH_SPAN,
                text=directive.spoken_text,
                display_text=directive.display_text,
                voice_name=voice,
                speed=directive.rate,
                chapter=chapter,
                instruction=directive.instruction,
                emotion=directive.emotion,
                emphasis=directive.emphasis,
                spell=directive.spell,
            )
        )
