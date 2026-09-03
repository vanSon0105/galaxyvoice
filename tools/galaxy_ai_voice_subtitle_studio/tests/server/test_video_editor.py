from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.common.errors import TaskCancelledError
from app.server.event_bus import event_bus
from app.server.main import create_app
from app.server.routers import video_editor as editor_router
from app.server.tasks import CANCELLED, DONE, task_registry
from app.video_editor.service import EditorExportResult, EditorMediaInfo
from app.video_editor.speech import EditorSpeechItemResult, EditorSpeechResult, EditorSpeechService


def _wait_status(task_id: str, timeout: float = 3.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = task_registry.get(task_id)
        if record is not None and record.status != "running":
            return record.status
        time.sleep(0.02)
    raise AssertionError(f"Task {task_id} did not finish")


class VideoEditorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="galaxy_editor_api_")
        self.root = Path(self._temp.name)
        self.video = self.root / "source.mp4"
        self.audio = self.root / "voice.wav"
        self.video.write_bytes(b"video")
        self.audio.write_bytes(b"audio")
        self.client = TestClient(create_app(config_path=self.root / "config.json"))
        task_registry._tasks.clear()
        editor_router.reset_editor_sources()

    def tearDown(self) -> None:
        self.client.close()
        self._temp.cleanup()

    def test_load_video_returns_seekable_opaque_url(self) -> None:
        with mock.patch.object(
            editor_router,
            "probe_editor_media",
            return_value=EditorMediaInfo(42.5, 1920, 1080, 29.97, True),
        ):
            response = self.client.post("/api/editor/load", json={"path": str(self.video), "kind": "video"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["duration_seconds"], 42.5)
        self.assertEqual(payload["width"], 1920)
        self.assertEqual(self.client.get(payload["url"]).content, b"video")

    def test_parse_srt_clamps_cues_to_video_duration(self) -> None:
        srt = self.root / "source.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:01,500\nXin chào\n\n"
            "2\n00:00:03,000 --> 00:00:05,000\nBị loại\n",
            encoding="utf-8",
        )
        response = self.client.post("/api/editor/cues", json={"path": str(srt), "duration_ms": 2_000})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["cues"]), 1)

    def test_export_passes_task_context_and_serves_result(self) -> None:
        captured: dict[str, object] = {}

        def fake_export(options, **kwargs):
            captured["options"] = options
            captured.update(kwargs)
            project = self.root / "edit"
            project.mkdir(exist_ok=True)
            video = project / "edit.mp4"
            video.write_bytes(b"edited")
            manifest = project / "editor_manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            return EditorExportResult(project, video, None, manifest, [])

        with mock.patch("app.video_editor.service.export_editor_video", side_effect=fake_export):
            response = self.client.post(
                "/api/editor/export",
                json={
                    "galaxy_project_id": "project-1",
                    "video_path": str(self.video),
                    "output_dir": str(self.root),
                    "segments": [
                        {"source_start_ms": 500, "source_end_ms": 1500},
                        {"source_start_ms": 3000, "source_end_ms": 4500},
                    ],
                },
            )
            task_id = response.json()["task_id"]
            self.assertEqual(_wait_status(task_id), DONE)

        record = task_registry.get(task_id)
        self.assertIs(captured["cancellation"], record.stop_event)
        self.assertEqual(captured["task_id"], task_id)
        self.assertEqual(
            [(segment.source_start_ms, segment.source_end_ms) for segment in captured["options"].video_segments],
            [(500, 1500), (3000, 4500)],
        )
        self.assertEqual(self.client.get(f"/api/files/task/{task_id}/edit.mp4").content, b"edited")
        graph = self.client.get("/api/project-graph/projects/project-1").json()
        self.assertEqual(graph["nodes"][0]["workspace"], "editor")
        self.assertEqual(
            {asset["role"] for asset in graph["nodes"][0]["assets"]},
            {"source_video", "edited_video", "manifest"},
        )

    def test_cancel_terminates_only_editor_processes(self) -> None:
        def wait_for_cancel(_options, *, cancellation, **_kwargs):
            cancellation.wait(2)
            raise TaskCancelledError()

        with (
            mock.patch("app.video_editor.service.export_editor_video", side_effect=wait_for_cancel),
            mock.patch.object(editor_router.managed_media_processes, "terminate_task") as terminate,
        ):
            task_id = self.client.post(
                "/api/editor/export",
                json={"video_path": str(self.video), "output_dir": str(self.root)},
            ).json()["task_id"]
            self.client.post(f"/api/tasks/{task_id}/cancel")
            self.assertEqual(_wait_status(task_id), CANCELLED)
            terminate.assert_called_once_with(task_id)

    def test_export_accepts_positioned_multitrack_clips(self) -> None:
        captured: dict[str, object] = {}

        def fake_export(options, **_kwargs):
            captured["options"] = options
            project = self.root / "multitrack"
            project.mkdir(exist_ok=True)
            video = project / "multitrack.mp4"
            video.write_bytes(b"edited")
            manifest = project / "editor_manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            return EditorExportResult(project, video, None, manifest, [])

        with mock.patch("app.video_editor.service.export_editor_video", side_effect=fake_export):
            response = self.client.post(
                "/api/editor/export",
                json={
                    "video_path": str(self.video),
                    "output_dir": str(self.root),
                    "video_clips": [{
                        "path": str(self.video), "timeline_start_ms": 0,
                        "source_start_ms": 0, "source_end_ms": 2_000,
                        "track_order": 1, "volume": 100, "has_audio": True,
                    }],
                    "audio_clips": [{
                        "path": str(self.audio), "timeline_start_ms": 500,
                        "source_start_ms": 0, "source_end_ms": 1_000,
                        "track_order": 2, "volume": 80, "has_audio": True,
                    }],
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(_wait_status(response.json()["task_id"]), DONE)

        options = captured["options"]
        self.assertEqual(options.video_clips[0].timeline_start_ms, 0)
        self.assertEqual(options.audio_clips[0].timeline_start_ms, 500)
        self.assertEqual(options.audio_clips[0].volume, 80)

    def test_speech_job_emits_each_completed_cue_with_editor_identity(self) -> None:
        audio = self.root / "generated.wav"
        audio.write_bytes(b"wav")

        def fake_execute(_service, spec, _engine, **callbacks):
            item = EditorSpeechItemResult(
                item_id="item-1",
                track_id="subtitle-2",
                cue_id="cue-7",
                start_ms=1_250,
                status="done",
                wav_path=str(audio),
            )
            callbacks["item_finished"](item)
            return EditorSpeechResult(spec.job_id, spec.project_id, str(self.root), (item,))

        engine = mock.Mock(code="sapi")
        with (
            mock.patch.object(EditorSpeechService, "execute", autospec=True, side_effect=fake_execute),
            mock.patch.object(editor_router, "create_tts_engine", return_value=engine, create=True),
            mock.patch.object(event_bus, "emit") as emit,
        ):
            response = self.client.post(
                "/api/editor/speech",
                json={
                    "job_id": "editor-job-1",
                    "project_id": "project-1",
                    "title": "Editor speech",
                    "output_dir": str(self.root),
                    "engine_id": "sapi",
                    "device": "cpu",
                    "voice": {"source": "auto"},
                    "engine_options": {"voice_name": "Microsoft David Desktop"},
                    "cues": [{
                        "item_id": "item-1",
                        "track_id": "subtitle-2",
                        "cue_id": "cue-7",
                        "start_ms": 1_250,
                        "text": "Xin chao",
                    }],
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["job_id"], "editor-job-1")
            task_id = response.json()["task_id"]
            self.assertEqual(_wait_status(task_id), DONE)

        record = task_registry.get(task_id)
        self.assertEqual(record.workflow_id, "editor-job-1")
        self.assertEqual(record.result_payload["items"][0]["cue_id"], "cue-7")
        emitted = [
            call.args[0]
            for call in emit.call_args_list
            if call.args[0].get("kind") == "editor_speech_item"
        ]
        self.assertEqual(emitted[0]["payload"]["task_id"], task_id)
        self.assertEqual(emitted[0]["payload"]["track_id"], "subtitle-2")


if __name__ == "__main__":
    unittest.main()
