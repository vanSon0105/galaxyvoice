from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..voice.audio import wav_duration_ms


@dataclass(frozen=True)
class SpeechTimingFitPolicy:
    tolerance_ms: int = 120
    max_safe_speed: float = 1.2


@dataclass(frozen=True)
class SpeechTimingFit:
    cue_duration_ms: int
    audio_duration_ms: int
    overflow_ms: int
    status: str
    suggested_speed: float | None = None

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def measure_speech_fit(
    wav_path: Path,
    *,
    cue_duration_ms: int,
    current_speed: float,
    policy: SpeechTimingFitPolicy | None = None,
) -> SpeechTimingFit:
    active_policy = policy or SpeechTimingFitPolicy()
    cue_duration = int(cue_duration_ms)
    speed = float(current_speed)
    if cue_duration <= 0:
        raise ValueError("Thời lượng câu phụ đề phải lớn hơn 0.")
    if speed <= 0:
        raise ValueError("Tốc độ tạo giọng phải lớn hơn 0.")

    audio_duration = wav_duration_ms(wav_path)
    if audio_duration <= 0:
        raise ValueError("Không đo được thời lượng audio đã tạo.")
    overflow = max(0, audio_duration - cue_duration)
    if overflow <= max(0, int(active_policy.tolerance_ms)):
        return SpeechTimingFit(cue_duration, audio_duration, overflow, "fits")

    required_speed = speed * audio_duration / cue_duration
    if required_speed <= max(speed, float(active_policy.max_safe_speed)):
        suggested = math.ceil((required_speed - 1e-9) * 100) / 100
        return SpeechTimingFit(
            cue_duration,
            audio_duration,
            overflow,
            "speed-up",
            round(suggested, 2),
        )
    return SpeechTimingFit(cue_duration, audio_duration, overflow, "condense")
