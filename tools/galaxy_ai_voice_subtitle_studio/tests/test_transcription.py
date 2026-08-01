from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.srt import SubtitleCue  # noqa: E402
from app.transcription import VideoSubtitleOptions, create_subtitles_from_video  # noqa: E402


class TranscriptionTests(unittest.TestCase):
    def test_create_subtitles_from_video_writes_original_and_translated_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"fake video")

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                Path(command[-1]).write_bytes(b"fake audio")
                return subprocess.CompletedProcess(command, 0, "", "")

            def transcriber(_audio_path, _language, _model, _progress):
                return [
                    SubtitleCue(index=1, start_ms=0, end_ms=1200, text="Hello."),
                    SubtitleCue(index=2, start_ms=1200, end_ms=2400, text="World."),
                ]

            def translator(cues, options):
                self.assertEqual(options.provider, "deepseek")
                self.assertEqual(options.model, "deepseek-v4-flash")
                self.assertEqual(options.base_url, "https://api.deepseek.com")
                return [
                    SubtitleCue(index=cue.index, start_ms=cue.start_ms, end_ms=cue.end_ms, text=f"VI {cue.text}")
                    for cue in cues
                ]

            with patch.dict(os.environ, {}, clear=True):
                with patch("app.env_config._read_windows_environment", return_value=""):
                    result = create_subtitles_from_video(
                        VideoSubtitleOptions(
                            video_path=video,
                            output_dir=root / "exports",
                            project_name="clip",
                            source_language="en",
                            target_language="vi",
                            ai_api_key="test-key",
                            ai_provider="deepseek",
                        ),
                        ffmpeg_path="ffmpeg",
                        runner=runner,
                        transcriber=transcriber,
                        translator=translator,
                    )

            self.assertTrue(result.audio_path.exists())
            self.assertTrue(result.source_srt_path.exists())
            self.assertTrue(result.translated_srt_path and result.translated_srt_path.exists())
            self.assertIn("Hello.", result.source_srt_path.read_text(encoding="utf-8"))
            self.assertIn("VI Hello.", result.translated_srt_path.read_text(encoding="utf-8"))
            self.assertEqual(result.script_text, "VI Hello.\nVI World.")
            self.assertEqual(result.script_language, "vi")
            self.assertIn("subtitle_manifest.json", str(result.manifest_path))
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["ai_provider"], "deepseek")


if __name__ == "__main__":
    unittest.main()
