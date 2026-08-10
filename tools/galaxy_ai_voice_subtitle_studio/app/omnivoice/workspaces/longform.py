from __future__ import annotations

import re
from dataclasses import dataclass

from ...voice.srt import SubtitleCue


SPEECH_SPAN = "speech"
PAUSE_SPAN = "pause"
_HEADING_RE = re.compile(r"^\s*#\s+(.+?)\s*$")
_CHARACTER_RE = re.compile(r"^\s*([^:\[\]\n]{1,48}):\s+(.+)$")
_TOKEN_RE = re.compile(
    r"\[voice:([^\[\]]*)\]"
    r"|\[pause(?:\s+(\d+(?:\.\d+)?)(?:\s*(ms|s))?)?\]"
    r"|\[(/?)(slow|fast|emphasis|spell)\]",
    re.IGNORECASE,
)


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


@dataclass(frozen=True)
class LongformPlan:
    spans: tuple[LongformSpan, ...]
    chapters: tuple[str, ...]

    @property
    def voice_names(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(span.voice_name for span in self.spans if span.voice_name)
        )


def parse_story_script(source: str) -> LongformPlan:
    return _parse_script(source, character_prefixes=True, default_chapter="Câu chuyện")


def parse_audiobook_script(source: str) -> LongformPlan:
    return _parse_script(source, character_prefixes=False, default_chapter="Nội dung")


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
) -> LongformPlan:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("Nội dung không được để trống.")
    spans: list[LongformSpan] = []
    chapters: list[str] = []
    chapter = default_chapter
    voice = ""
    speed = 1.0
    spell = False
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
        line_spans, voice, speed, spell = _parse_markup(
            line,
            voice=voice,
            speed=speed,
            spell=spell,
            chapter=chapter,
        )
        spans.extend(line_spans)
    if not any(span.kind == SPEECH_SPAN for span in spans):
        raise ValueError("Nội dung không có đoạn thoại nào để tạo giọng.")
    return LongformPlan(spans=tuple(spans), chapters=tuple(chapters))


def _parse_markup(
    text: str,
    *,
    voice: str,
    speed: float,
    spell: bool,
    chapter: str,
) -> tuple[list[LongformSpan], str, float, bool]:
    spans: list[LongformSpan] = []
    cursor = 0
    for match in _TOKEN_RE.finditer(text):
        if match.start() > cursor:
            _append_speech(spans, text[cursor : match.start()], voice, speed, spell, chapter)
        if match.group(1) is not None:
            selected = match.group(1).strip()
            voice = "" if selected.casefold() in {"", "default"} else selected
        elif match.group(2) is not None or match.group(0).lower().startswith("[pause"):
            value = float(match.group(2) or 500)
            pause_ms = round(value * 1000 if (match.group(3) or "").lower() == "s" else value)
            spans.append(LongformSpan(kind=PAUSE_SPAN, pause_ms=max(0, min(10_000, pause_ms)), chapter=chapter))
        else:
            closing = bool(match.group(4))
            tag = (match.group(5) or "").lower()
            if tag == "slow":
                speed = 1.0 if closing else 0.85
            elif tag == "fast":
                speed = 1.0 if closing else 1.15
            elif tag == "spell":
                spell = not closing
        cursor = match.end()
    if cursor < len(text):
        _append_speech(spans, text[cursor:], voice, speed, spell, chapter)
    return spans, voice, speed, spell


def _append_speech(
    spans: list[LongformSpan],
    text: str,
    voice: str,
    speed: float,
    spell: bool,
    chapter: str,
) -> None:
    cleaned = text.strip()
    if not cleaned:
        return
    if spell:
        cleaned = " ".join(character for character in cleaned if not character.isspace())
    spans.append(
        LongformSpan(
            kind=SPEECH_SPAN,
            text=cleaned,
            voice_name=voice,
            speed=speed,
            chapter=chapter,
        )
    )
