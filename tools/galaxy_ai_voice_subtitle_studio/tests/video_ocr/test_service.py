from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.video_ocr.models import VideoOcrOptions, VideoOcrRegion
from app.video_ocr.service import VideoOcrRuntime, build_video_ocr_command, recognize_burned_subtitles


class VideoOcrServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="galaxy_ocr_service_")
        self.root = Path(self.temp.name)
        self.video = self.root / "source.mp4"
        self.video.write_bytes(b"video")
        self.python = self.root / "python.exe"
        self.python.write_bytes(b"python")
        self.runtime = VideoOcrRuntime(self.root, self.python)
        self.options = VideoOcrOptions(
            self.video,
            self.root / "output",
            "captured",
            "fast",
            VideoOcrRegion(5, 70, 90, 25),
            "vi",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_command_keeps_region_and_mode_explicit(self) -> None:
        command = build_video_ocr_command(
            self.runtime,
            self.root / "worker.py",
            self.options,
            self.root / "result",
        )
        self.assertEqual(command[command.index("--mode") + 1], "fast")
        self.assertEqual(command[-4:], ["5", "70", "90", "25"])

    def test_reuses_cached_result_without_running_worker_again(self) -> None:
        def fake_worker(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "captions.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nXin chao\n",
                encoding="utf-8",
            )
            (output / "ocr_manifest.json").write_text(
                json.dumps({
                    "sampled_frames": 10,
                    "ocr_frames": 3,
                    "reused_frames": 7,
                    "cues": [{
                        "index": 1,
                        "start_ms": 0,
                        "end_ms": 1_000,
                        "text": "Xin chao",
                        "confidence": 0.9,
                        "boxes": [],
                    }],
                }),
                encoding="utf-8",
            )
            return 0, []

        cache = self.root / "cache"
        with mock.patch("app.video_ocr.service._run_worker", side_effect=fake_worker) as worker:
            first = recognize_burned_subtitles(self.options, runtime=self.runtime, cache_root=cache)
            second = recognize_burned_subtitles(self.options, runtime=self.runtime, cache_root=cache)

        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.cues[0].text, "Xin chao")
        worker.assert_called_once()


if __name__ == "__main__":
    unittest.main()
