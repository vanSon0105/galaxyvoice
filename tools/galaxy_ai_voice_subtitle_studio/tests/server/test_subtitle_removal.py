from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.common.errors import TaskCancelledError
from app.server.main import create_app
from app.server.routers import subtitle_removal as removal_router
from app.server.tasks import CANCELLED, DONE, task_registry
from app.subtitle_removal.service import SubtitleRemovalResult


def _wait_status(task_id: str, timeout: float = 3.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = task_registry.get(task_id)
        if record is not None and record.status != "running":
            return record.status
        time.sleep(0.02)
    raise AssertionError(f"Task {task_id} did not finish")


class SubtitleRemovalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="galaxy_removal_api_")
        self.root = Path(self._temp.name)
        self.video = self.root / "source.mp4"
        self.video.write_bytes(b"video")
        self.client = TestClient(create_app(config_path=self.root / "config.json"))
        task_registry._tasks.clear()
        removal_router.reset_removal_sources()

    def tearDown(self) -> None:
        self.client.close()
        self._temp.cleanup()

    def test_modes_expose_all_five_backends(self) -> None:
        with mock.patch.object(removal_router, "resolve_propainter_runtime", side_effect=RuntimeError()):
            response = self.client.get("/api/removal/modes")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["modes"]), 5)
        self.assertEqual({item["code"] for item in payload["modes"]}, {
            "strip", "blur", "fill", "ai_inpaint", "fast_ai_inpaint",
        })
        self.assertFalse(payload["propainter_ready"])

    def test_registered_video_is_seekable_from_opaque_source_url(self) -> None:
        with (
            mock.patch.object(removal_router, "probe_video_size", return_value=(1920, 1080)),
            mock.patch.object(removal_router, "probe_video_duration", return_value=42.5),
        ):
            response = self.client.post("/api/removal/source", json={"video_path": str(self.video)})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["width"], 1920)
        self.assertEqual(payload["duration"], 42.5)
        streamed = self.client.get(payload["url"])
        self.assertEqual(streamed.status_code, 200)
        self.assertEqual(streamed.content, b"video")

    def test_preview_uses_requested_scrub_time(self) -> None:
        def fake_preview(_video, output, timestamp_seconds=0, **_kwargs):
            self.assertEqual(timestamp_seconds, 12.75)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"jpeg")
            return output

        with mock.patch.object(removal_router, "create_video_preview", side_effect=fake_preview):
            response = self.client.post(
                "/api/removal/preview",
                json={"video_path": str(self.video), "timestamp_seconds": 12.75},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"jpeg")

    def test_ai_mode_requires_license_acceptance(self) -> None:
        response = self.client.post(
            "/api/removal/remove",
            json={
                "video_path": str(self.video),
                "output_dir": str(self.root),
                "mode": "fast_ai_inpaint",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("license", response.json()["detail"].lower())

    def test_removal_task_returns_playable_video_and_passes_task_context(self) -> None:
        captured: dict[str, object] = {}

        def fake_remove(options, **kwargs):
            captured.update(kwargs)
            project = self.root / "clean"
            project.mkdir(exist_ok=True)
            video = project / "clean_no_subtitles.mp4"
            video.write_bytes(b"clean")
            manifest = project / "subtitle_removal_manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            return SubtitleRemovalResult(project, video, manifest, options.mode, [])

        with mock.patch("app.subtitle_removal.service.remove_subtitles_from_video", side_effect=fake_remove):
            response = self.client.post(
                "/api/removal/remove",
                json={
                    "galaxy_project_id": "project-1",
                    "video_path": str(self.video),
                    "output_dir": str(self.root),
                    "mode": "blur",
                },
            )
            task_id = response.json()["task_id"]
            self.assertEqual(_wait_status(task_id), DONE)

        record = task_registry.get(task_id)
        self.assertIs(captured["stop_event"], record.stop_event)
        self.assertEqual(captured["task_id"], task_id)
        served = self.client.get(f"/api/files/task/{task_id}/clean_no_subtitles.mp4")
        self.assertEqual(served.status_code, 200)
        graph = self.client.get("/api/project-graph/projects/project-1").json()
        self.assertEqual(graph["nodes"][0]["workspace"], "subtitle_removal")
        self.assertIn("clean_video", {asset["role"] for asset in graph["nodes"][0]["assets"]})

    def test_cancel_terminates_only_subtitle_removal_processes(self) -> None:
        def wait_for_cancel(_options, *, stop_event, **_kwargs):
            stop_event.wait(2)
            raise TaskCancelledError()

        with (
            mock.patch("app.subtitle_removal.service.remove_subtitles_from_video", side_effect=wait_for_cancel),
            mock.patch.object(removal_router.managed_media_processes, "terminate_task") as terminate,
        ):
            response = self.client.post(
                "/api/removal/remove",
                json={"video_path": str(self.video), "output_dir": str(self.root)},
            )
            task_id = response.json()["task_id"]
            self.client.post(f"/api/tasks/{task_id}/cancel")
            self.assertEqual(_wait_status(task_id), CANCELLED)
            terminate.assert_called_once_with(task_id)


if __name__ == "__main__":
    unittest.main()
