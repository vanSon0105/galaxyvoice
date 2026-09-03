from __future__ import annotations

import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.voice.audio import concatenate_wavs, split_wav_on_silence, wav_duration_ms  # noqa: E402


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

    def test_splits_wav_only_when_expected_silence_boundaries_are_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "cluster.wav"
            first = root / "first.wav"
            second = root / "second.wav"
            _write_tone_and_silence_wav(source, (300, 200, 500))

            split = split_wav_on_silence(source, [first, second], weights=[3, 5])

            self.assertTrue(split)
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
            self.assertEqual(wav_duration_ms(first) + wav_duration_ms(second), 1_000)

    def test_refuses_unproven_wav_split_and_leaves_no_partial_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "cluster.wav"
            outputs = [root / "first.wav", root / "second.wav"]
            _write_tone_and_silence_wav(source, (1_000,))

            self.assertFalse(split_wav_on_silence(source, outputs, weights=[1, 1]))
            self.assertFalse(any(path.exists() for path in outputs))

    def test_ignores_leading_and_trailing_silence_when_proving_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "cluster.wav"
            outputs = [root / "first.wav", root / "second.wav"]
            _write_pcm_sections(
                source,
                ((0, 100), (12_000, 300), (0, 200), (12_000, 500), (0, 100)),
            )

            self.assertTrue(split_wav_on_silence(source, outputs, weights=[3, 5]))
            self.assertTrue(all(path.is_file() for path in outputs))

    def test_refuses_split_when_extra_internal_silence_makes_alignment_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "cluster.wav"
            outputs = [root / "first.wav", root / "second.wav"]
            _write_tone_and_silence_wav(source, (200, 150, 200, 150, 300))

            self.assertFalse(split_wav_on_silence(source, outputs, weights=[2, 3]))
            self.assertFalse(any(path.exists() for path in outputs))


def _write_silent_wav(path: Path, duration_ms: int) -> None:
    framerate = 1000
    frames = duration_ms
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(framerate)
        handle.writeframes(b"\x00\x00" * frames)


def _write_tone_and_silence_wav(path: Path, durations_ms: tuple[int, ...]) -> None:
    sections = tuple((12_000 if index % 2 == 0 else 0, duration_ms) for index, duration_ms in enumerate(durations_ms))
    _write_pcm_sections(path, sections)


def _write_pcm_sections(path: Path, sections: tuple[tuple[int, int], ...]) -> None:
    frames = bytearray()
    for amplitude, duration_ms in sections:
        sample = amplitude.to_bytes(2, "little", signed=True)
        frames.extend(sample * duration_ms)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(1_000)
        handle.writeframes(frames)


if __name__ == "__main__":
    unittest.main()
