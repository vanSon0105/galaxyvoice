from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.media import (  # noqa: E402
    MediaExtractionOptions,
    build_extract_wav_command,
    extract_audio_from_video,
)


class MediaTests(unittest.TestCase):
    def test_build_extract_wav_command_targets_speech_to_text_format(self) -> None:
        command = build_extract_wav_command("ffmpeg", Path("clip.mp4"), Path("audio.wav"))

        self.assertIn("-ac", command)
        self.assertIn("1", command)
        self.assertIn("-ar", command)
        self.assertIn("16000", command)
        self.assertEqual(command[-1], "audio.wav")

    def test_extract_audio_writes_outputs_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "source.mp4"
            video.write_bytes(b"fake video")
            commands: list[list[str]] = []

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                Path(command[-1]).write_bytes(b"fake audio")
                return subprocess.CompletedProcess(command, 0, "", "")

            result = extract_audio_from_video(
                MediaExtractionOptions(video_path=video, output_dir=root / "exports", project_name="clip"),
                ffmpeg_path="ffmpeg",
                runner=runner,
            )

            self.assertEqual(len(commands), 2)
            self.assertTrue(result.wav_path and result.wav_path.exists())
            self.assertTrue(result.mp3_path and result.mp3_path.exists())
            self.assertTrue(result.manifest_path.exists())
            self.assertIn("source.mp4", result.manifest_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
