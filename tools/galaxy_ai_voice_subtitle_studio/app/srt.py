from __future__ import annotations

from dataclasses import dataclass


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
