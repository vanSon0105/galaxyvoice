from __future__ import annotations

import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.engine import GenerationOptions, generate_package  # noqa: E402


class FakeTTS:
    code = "fake"
    label = "Fake TTS"

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


class FailingTTS(FakeTTS):
    def synthesize_to_wav(
        self,
        text: str,
        output_path: Path,
        voice_name: str | None = None,
        rate: int = 0,
        volume: int = 100,
    ) -> None:
        raise RuntimeError("provider returned no audio")


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
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["tts_engine"], "fake")

    def test_edge_tts_is_the_default_engine(self) -> None:
        edge = FakeTTS()
        edge.code = "edge"
        edge.label = "Edge TTS (Online)"

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.engine.EdgeTTS", return_value=edge):
                result = generate_package(
                    GenerationOptions(
                        text="Xin chao.",
                        output_dir=Path(temp_dir),
                        project_name="edge-default",
                        export_mp3=False,
                    )
                )

            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["tts_engine"], "edge")

    def test_generation_error_identifies_the_failed_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, r"Segment 1/1 failed.*Xin chao"):
                generate_package(
                    GenerationOptions(
                        text="Xin chao.",
                        output_dir=Path(temp_dir),
                        export_mp3=False,
                    ),
                    tts=FailingTTS(),  # type: ignore[arg-type]
                )


if __name__ == "__main__":
    unittest.main()
