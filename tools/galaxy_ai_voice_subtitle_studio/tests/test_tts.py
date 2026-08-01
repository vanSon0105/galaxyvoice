from __future__ import annotations

import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.tts import EdgeTTS  # noqa: E402


class FakeCommunicate:
    calls: list[dict[str, str]] = []

    def __init__(self, text: str, voice: str, *, rate: str, volume: str) -> None:
        self.call = {
            "text": text,
            "voice": voice,
            "rate": rate,
            "volume": volume,
        }
        self.calls.append(self.call)

    async def save(self, output_path: str) -> None:
        Path(output_path).write_bytes(b"fake mp3")


class FakeEdgeModule:
    Communicate = FakeCommunicate

    @staticmethod
    async def list_voices() -> list[dict[str, str]]:
        return [
            {
                "ShortName": "en-US-GuyNeural",
                "Locale": "en-US",
                "Gender": "Male",
            },
            {
                "ShortName": "vi-VN-NamMinhNeural",
                "Locale": "vi-VN",
                "Gender": "Male",
            },
            {
                "ShortName": "vi-VN-HoaiMyNeural",
                "Locale": "vi-VN",
                "Gender": "Female",
            },
        ]


class EdgeTTSTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeCommunicate.calls.clear()

    def test_lists_vietnamese_voice_first(self) -> None:
        voices = EdgeTTS(edge_module=FakeEdgeModule).list_voices()

        self.assertEqual(voices[0].name, "vi-VN-HoaiMyNeural")
        self.assertEqual(voices[0].culture, "vi-VN")
        self.assertEqual(voices[0].gender, "Female")
        self.assertEqual(voices[1].name, "vi-VN-NamMinhNeural")

    def test_synthesizes_edge_audio_and_converts_it_to_wav(self) -> None:
        engine = EdgeTTS(edge_module=FakeEdgeModule)

        def write_wav(_source: Path, output: Path) -> None:
            with wave.open(str(output), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(24000)
                handle.writeframes(b"\x00\x00" * 100)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "voice.wav"
            with patch("app.tts.find_ffmpeg", return_value="ffmpeg"):
                with patch("app.tts._convert_edge_audio_to_wav", side_effect=write_wav) as convert:
                    engine.synthesize_to_wav(
                        "Xin chao Viet Nam.",
                        output_path,
                        voice_name="vi-VN-NamMinhNeural",
                        rate=2,
                        volume=80,
                    )

            self.assertTrue(output_path.exists())
            self.assertEqual(
                FakeCommunicate.calls,
                [
                    {
                        "text": "Xin chao Viet Nam.",
                        "voice": "vi-VN-NamMinhNeural",
                        "rate": "+20%",
                        "volume": "-20%",
                    }
                ],
            )
            convert.assert_called_once()

    def test_reports_unavailable_without_ffmpeg(self) -> None:
        with patch("app.tts.find_ffmpeg", return_value=None):
            engine = EdgeTTS(edge_module=FakeEdgeModule)

            self.assertFalse(engine.available())
            self.assertIn("ffmpeg", engine.unavailable_reason())

    def test_reports_install_command_when_package_is_missing(self) -> None:
        with patch("app.tts.find_ffmpeg", return_value="ffmpeg"):
            with patch("app.tts.importlib.import_module", side_effect=ImportError):
                reason = EdgeTTS().unavailable_reason()

        self.assertIn("pip install -r requirements-voice.txt", reason)


if __name__ == "__main__":
    unittest.main()
