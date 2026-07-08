from __future__ import annotations

import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.audio import concatenate_wavs, wav_duration_ms  # noqa: E402


class AudioTests(unittest.TestCase):
    def test_concatenates_wavs_and_reports_timings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.wav"
            second = root / "second.wav"
            output = root / "combined.wav"

            _write_silent_wav(first, duration_ms=100)
            _write_silent_wav(second, duration_ms=50)

            timings = concatenate_wavs([first, second], output, gap_ms=25)

            self.assertEqual(timings[0].start_ms, 0)
            self.assertEqual(timings[0].end_ms, 100)
            self.assertEqual(timings[1].start_ms, 125)
            self.assertEqual(timings[1].end_ms, 175)
            self.assertEqual(wav_duration_ms(output), 175)


def _write_silent_wav(path: Path, duration_ms: int) -> None:
    framerate = 1000
    frames = duration_ms
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(framerate)
        handle.writeframes(b"\x00\x00" * frames)


if __name__ == "__main__":
    unittest.main()
