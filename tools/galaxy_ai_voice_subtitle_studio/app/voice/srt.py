from __future__ import annotations

import re
from dataclasses import dataclass


_TIMESTAMP_PATTERN = re.compile(
    r"^(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})\s*-->\s*"
    r"(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})$"
)


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start_ms: int
    end_ms: int
    text: str


def format_timestamp(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def render_srt(cues: list[SubtitleCue]) -> str:
    blocks: list[str] = []

    for cue in cues:
        end_ms = max(cue.end_ms, cue.start_ms + 1)
        blocks.append(
            "\n".join(
                [
                    str(cue.index),
                    f"{format_timestamp(cue.start_ms)} --> {format_timestamp(end_ms)}",
                    cue.text.strip(),
                ]
            )
        )

    return "\n\n".join(blocks) + ("\n" if blocks else "")


def parse_srt(text: str) -> list[SubtitleCue]:
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    cues: list[SubtitleCue] = []
    for block in re.split(r"\n[ \t]*\n", normalized):
        lines = block.splitlines()
        if len(lines) < 3:
            raise ValueError("Invalid SRT cue: expected an index, timing, and subtitle text.")
        try:
            index = int(lines[0].strip())
        except ValueError as error:
            raise ValueError(f"Invalid SRT cue index: {lines[0]}") from error

        match = _TIMESTAMP_PATTERN.fullmatch(lines[1].strip())
        if match is None:
            raise ValueError(f"Invalid SRT timing: {lines[1]}")
        values = [int(value) for value in match.groups()]
        start_ms = _timestamp_to_milliseconds(*values[:4])
        end_ms = _timestamp_to_milliseconds(*values[4:])
        if end_ms <= start_ms:
            raise ValueError(f"Invalid SRT timing for cue {index}: end must be after start.")

        cue_text = "\n".join(lines[2:]).strip()
        if not cue_text:
            raise ValueError(f"Invalid SRT cue {index}: subtitle text is empty.")
        cues.append(SubtitleCue(index=index, start_ms=start_ms, end_ms=end_ms, text=cue_text))

    return cues


def _timestamp_to_milliseconds(hours: int, minutes: int, seconds: int, milliseconds: int) -> int:
    return hours * 3_600_000 + minutes * 60_000 + seconds * 1_000 + milliseconds
