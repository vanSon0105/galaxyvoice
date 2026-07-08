from __future__ import annotations

import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.engine import GenerationOptions, generate_package  # noqa: E402


class FakeTTS:
    def available(self) -> bool:
        return True

    def synthesize_to_wav(
        self,
        text: str,
        output_path: Path,
        voice_name: str | None = None,
        rate: int = 0,
        volume: int = 100,
    ) -> None:
        duration_ms = max(40, len(text))
        with wave.open(str(output_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(1000)
            handle.writeframes(b"\x00\x00" * duration_ms)


class EngineTests(unittest.TestCase):
    def test_generate_package_writes_audio_srt_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate_package(
                GenerationOptions(
                    text="Xin chao. Day la ban test.",
                    output_dir=Path(temp_dir),
                    project_name="demo",
                    export_mp3=False,
                ),
                tts=FakeTTS(),  # type: ignore[arg-type]
            )

            self.assertEqual(result.cue_count, 2)
            self.assertTrue(result.wav_path.exists())
            self.assertTrue(result.srt_path.exists())
            self.assertTrue(result.manifest_path.exists())
            self.assertIn("00:00:00,000 -->", result.srt_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
