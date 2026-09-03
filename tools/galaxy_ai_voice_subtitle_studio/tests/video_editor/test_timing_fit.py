from __future__ import annotations

import tempfile
import wave
from pathlib import Path

from app.video_editor.timing_fit import SpeechTimingFitPolicy, measure_speech_fit


def test_fit_reports_small_tolerance_without_suggesting_a_change() -> None:
    with tempfile.TemporaryDirectory(prefix="galaxy_fit_") as temp_dir:
        wav_path = Path(temp_dir) / "voice.wav"
        _write_wav(wav_path, 1_080)

        fit = measure_speech_fit(wav_path, cue_duration_ms=1_000, current_speed=1.0)

    assert fit.status == "fits"
    assert fit.audio_duration_ms == 1_080
    assert fit.cue_duration_ms == 1_000
    assert fit.overflow_ms == 80
    assert fit.suggested_speed is None


def test_fit_suggests_only_a_bounded_safe_speed() -> None:
    with tempfile.TemporaryDirectory(prefix="galaxy_fit_") as temp_dir:
        root = Path(temp_dir)
        safe_path = root / "safe.wav"
        unsafe_path = root / "unsafe.wav"
        _write_wav(safe_path, 1_150)
        _write_wav(unsafe_path, 1_400)
        policy = SpeechTimingFitPolicy(max_safe_speed=1.2)

        safe = measure_speech_fit(
            safe_path,
            cue_duration_ms=1_000,
            current_speed=1.0,
            policy=policy,
        )
        unsafe = measure_speech_fit(
            unsafe_path,
            cue_duration_ms=1_000,
            current_speed=1.0,
            policy=policy,
        )

    assert safe.status == "speed-up"
    assert safe.suggested_speed == 1.15
    assert unsafe.status == "condense"
    assert unsafe.suggested_speed is None


def _write_wav(path: Path, duration_ms: int) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(1_000)
        output.writeframes((12_000).to_bytes(2, "little", signed=True) * duration_ms)
