from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.server.main import create_app
from app.server.tasks import DONE, task_registry
from app.video_ocr.models import OcrCue, VideoOcrResult
from app.video_ocr.service import VideoOcrRuntime


def _wait(task_id: str) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        record = task_registry.get(task_id)
        if record is not None and record.status == DONE:
            return
        time.sleep(0.02)
    raise AssertionError(f"Task {task_id} did not finish")


class VideoOcrApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="galaxy_ocr_api_")
        self.root = Path(self.temp.name)
        self.video = self.root / "source.mp4"
        self.video.write_bytes(b"video")
        self.runtime_python = self.root / "python.exe"
        self.runtime_python.write_bytes(b"python")
        self.client = TestClient(create_app(config_path=self.root / "config.json"))
        task_registry._tasks.clear()

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def test_recognize_runs_as_task_and_returns_srt_asset(self) -> None:
        project = self.root / "ocr-result"
        project.mkdir()
        srt = project / "captions.srt"
        manifest = project / "ocr_manifest.json"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chao\n", encoding="utf-8")
        manifest.write_text("{}", encoding="utf-8")
        result = VideoOcrResult(
            project,
            srt,
            manifest,
            self.video,
            (OcrCue(1, 0, 1_000, "Xin chao", 0.95),),
            20,
            6,
            14,
        )
        runtime = VideoOcrRuntime(self.root, self.runtime_python)
        with (
            mock.patch("app.server.routers.video_ocr.default_video_ocr_runtime", return_value=runtime),
            mock.patch("app.server.routers.video_ocr.recognize_burned_subtitles", return_value=result) as recognize,
        ):
            response = self.client.post(
                "/api/editor/ocr/recognize",
                json={
                    "video_path": str(self.video),
                    "output_dir": str(self.root),
                    "mode": "fast",
                    "region": {"x": 5, "y": 70, "width": 90, "height": 25},
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            task_id = response.json()["task_id"]
            _wait(task_id)

        options = recognize.call_args.args[0]
        self.assertEqual(options.region.as_tuple(), (5, 70, 90, 25))
        payload = task_registry.get(task_id).result_payload
        self.assertEqual(payload["srt_path"], str(srt))
        self.assertEqual(payload["cues"][0]["text"], "Xin chao")
        self.assertEqual(payload["reused_frames"], 14)

    def test_rejects_out_of_bounds_region(self) -> None:
        response = self.client.post(
            "/api/editor/ocr/recognize",
            json={
                "video_path": str(self.video),
                "output_dir": str(self.root),
                "region": {"x": 20, "y": 80, "width": 90, "height": 30},
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_rejects_empty_output_directory(self) -> None:
        response = self.client.post(
            "/api/editor/ocr/recognize",
            json={
                "video_path": str(self.video),
                "output_dir": "   ",
            },
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
