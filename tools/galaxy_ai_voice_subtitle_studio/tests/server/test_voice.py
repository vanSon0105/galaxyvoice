"""Video Dubbing router tests with monkeypatched services (no real TTS/ffmpeg)."""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.common.errors import TaskCancelledError
from app.server.main import create_app
from app.server.routers import voice as voice_router
from app.server.tasks import CANCELLED, DONE, FAILED, task_registry
from app.voice.engine import GenerationResult
from app.voice.media import MediaExtractionResult
from app.voice.srt import SubtitleCue, render_srt
from app.voice.transcription import VideoSubtitleDraft, VideoSubtitleResult


def _wait_status(task_id: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = task_registry.get(task_id)
        if record is not None and record.status != "running":
            return record.status
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish in time")


def _make_generation_result(tmp: Path) -> GenerationResult:
    project_dir = tmp / "gen_project"
    project_dir.mkdir()
    wav = project_dir / "gen.wav"
    wav.write_bytes(b"RIFF")
    srt = project_dir / "gen.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chào\n", encoding="utf-8")
    manifest = project_dir / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    return GenerationResult(
        project_dir=project_dir,
        wav_path=wav,
        srt_path=srt,
        mp3_path=None,
        manifest_path=manifest,
        cue_count=1,
        total_duration_ms=1000,
        warnings=[],
    )


class VoiceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="galaxy_test_voice_")
        self.tmp = Path(self._tmp.name)
        self.client = TestClient(create_app(config_path=self.tmp / "config.json"))
        task_registry._tasks.clear()
        with voice_router._drafts_lock:
            for draft in list(voice_router._drafts.values()):
                draft.cleanup()
            voice_router._drafts.clear()
            voice_router._draft_edits.clear()

    def tearDown(self) -> None:
        self.client.close()
        self._tmp.cleanup()

    def test_engines_lists_edge_and_sapi(self) -> None:
        response = self.client.get("/api/voice/engines")
        self.assertEqual(response.status_code, 200)
        codes = [engine["code"] for engine in response.json()]
        self.assertIn("edge", codes)
        self.assertIn("sapi", codes)

    def test_voices_endpoint_calls_engine_list(self) -> None:
        with mock.patch.object(voice_router, "create_tts_engine") as create_engine:
            fake = mock.Mock()
            fake.list_voices.return_value = []
            create_engine.return_value = fake
            response = self.client.get("/api/voice/voices", params={"engine": "edge"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_generate_task_reports_progress_and_done(self) -> None:
        with mock.patch.object(voice_router, "generate_package") as generate:
            generate.side_effect = lambda options, tts, progress, stop_event: (
                progress("đang tạo 1/1"),
                _make_generation_result(self.tmp),
            )[1]

            with self.client.websocket_connect("/ws/events") as websocket:
                response = self.client.post(
                    "/api/voice/generate",
                    json={"text": "Xin chào", "output_dir": str(self.tmp)},
                )
                self.assertEqual(response.status_code, 200)
                task_id = response.json()["task_id"]

                running = websocket.receive_json()
                self.assertEqual(running["type"], "task")
                self.assertEqual(running["status"], "running")

                messages = [websocket.receive_json() for _ in range(2)]
                kinds = {message["type"] for message in messages}
                self.assertIn("progress", kinds)
                self.assertIn("task", kinds)

                self.assertEqual(_wait_status(task_id), DONE)
                record = task_registry.get(task_id)
                self.assertEqual(record.result.wav_path.name, "gen.wav")

    def test_generate_task_cancel_maps_to_cancelled(self) -> None:
        def slow_generate(options, tts, progress, stop_event):
            while not stop_event.is_set():
                time.sleep(0.05)
            raise TaskCancelledError()

        with mock.patch.object(voice_router, "generate_package", side_effect=slow_generate):
            response = self.client.post(
                "/api/voice/generate",
                json={"text": "Xin chào", "output_dir": str(self.tmp)},
            )
            task_id = response.json()["task_id"]
            time.sleep(0.1)
            cancel = self.client.post(f"/api/tasks/{task_id}/cancel")
            self.assertEqual(cancel.status_code, 200)
            self.assertEqual(_wait_status(task_id), CANCELLED)

    def test_generate_task_failure_maps_to_failed(self) -> None:
        with mock.patch.object(
            voice_router, "generate_package", side_effect=RuntimeError("hỏng rồi")
        ):
            response = self.client.post(
                "/api/voice/generate",
                json={"text": "Xin chào", "output_dir": str(self.tmp)},
            )
            task_id = response.json()["task_id"]
            self.assertEqual(_wait_status(task_id), FAILED)
            self.assertEqual(task_registry.get(task_id).error, "hỏng rồi")

    def test_generate_translates_script_in_flow_when_target_differs(self) -> None:
        with mock.patch.object(
            voice_router, "translate_script_text", return_value="Hello world"
        ) as translate, mock.patch.object(voice_router, "generate_package") as generate:
            generate.side_effect = (
                lambda options, tts, progress, stop_event: _make_generation_result(self.tmp)
            )
            with self.client.websocket_connect("/ws/events") as websocket:
                response = self.client.post(
                    "/api/voice/generate",
                    json={
                        "text": "Xin chào",
                        "output_dir": str(self.tmp),
                        "source_language": "vi",
                        "target_language": "en",
                        "ai_provider": "openai",
                        "ai_api_key": "sk-test",
                    },
                )
                task_id = response.json()["task_id"]
                self.assertEqual(_wait_status(task_id), DONE)

                done_frame = None
                for _ in range(6):
                    frame = websocket.receive_json()
                    if frame.get("type") == "task" and frame.get("status") == DONE:
                        done_frame = frame
                        break
                self.assertIsNotNone(done_frame)
                self.assertEqual(done_frame["result"]["translated_text"], "Hello world")
                self.assertEqual(done_frame["result"]["target_language"], "en")
                self.assertEqual(translate.call_args[0][0], "Xin chào")
                self.assertEqual(generate.call_args[0][0].text, "Hello world")

    def test_extract_audio_task_runs(self) -> None:
        with mock.patch.object(voice_router, "extract_audio_from_video") as extract:
            project_dir = self.tmp / "media_project"
            project_dir.mkdir()
            extract.return_value = MediaExtractionResult(
                project_dir=project_dir,
                wav_path=None,
                mp3_path=None,
                manifest_path=project_dir / "media_manifest.json",
                warnings=[],
            )
            response = self.client.post(
                "/api/voice/extract-audio",
                json={"video_path": str(self.tmp / "video.mp4"), "output_dir": str(self.tmp)},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(_wait_status(response.json()["task_id"]), DONE)

    def test_transcribe_draft_flow(self) -> None:
        workspace = tempfile.TemporaryDirectory(prefix="galaxy_test_draft_")
        audio_path = Path(workspace.name) / "speech.wav"
        audio_path.write_bytes(b"RIFF")
        cues = [
            SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Xin chào"),
            SubtitleCue(index=2, start_ms=1200, end_ms=2200, text="Tạm biệt"),
        ]

        def fake_prepare(options, progress=None, stop_event=None, **kwargs):
            return VideoSubtitleDraft(
                source_video=Path(options.video_path),
                project_name=options.project_name or "video",
                audio_path=audio_path,
                source_language="vi",
                target_language="en",
                whisper_model="base",
                ai_provider="openai",
                ai_model="gpt-test",
                ai_base_url="https://example.test/v1",
                source_cues=tuple(cues),
                translated_cues=tuple(
                    SubtitleCue(index=cue.index, start_ms=cue.start_ms, end_ms=cue.end_ms, text=f"EN{cue.index}")
                    for cue in cues
                ),
                warnings=[],
                _workspace=None,
            )

        with mock.patch.object(voice_router, "prepare_subtitles_from_video", side_effect=fake_prepare):
            response = self.client.post(
                "/api/voice/transcribe",
                json={
                    "video_path": str(self.tmp / "video.mp4"),
                    "output_dir": str(self.tmp),
                    "target_language": "en",
                },
            )
            task_id = response.json()["task_id"]
            self.assertEqual(_wait_status(task_id), DONE)

            draft = self.client.get(f"/api/voice/draft/{task_id}")
            self.assertEqual(draft.status_code, 200)
            body = draft.json()
            self.assertEqual(body["source_language"], "vi")
            self.assertIn("Xin chào", body["source_srt"])
            self.assertIn("EN1", body["translated_srt"])

            # Valid edit round-trip.
            edited_source = render_srt(list(cues))
            edited = self.client.put(
                f"/api/voice/draft/{task_id}",
                json={"source_srt": edited_source},
            )
            self.assertEqual(edited.status_code, 200)
            self.assertEqual(edited.json()["source_srt"].strip(), edited_source.strip())

            # Mismatched cue counts are rejected.
            bad = self.client.put(
                f"/api/voice/draft/{task_id}",
                json={"translated_srt": "1\n00:00:00,000 --> 00:00:01,000\nonly one\n"},
            )
            self.assertEqual(bad.status_code, 422)

            # Export.
            export_dir = self.tmp / "exports"
            export_dir.mkdir()
            exported = self.client.post(
                f"/api/voice/draft/{task_id}/export",
                json={"output_dir": str(export_dir), "project_name": "test_export"},
            )
            self.assertEqual(exported.status_code, 200)
            self.assertEqual(exported.json()["cue_count"], 2)

        workspace.cleanup()

    def test_draft_endpoints_404_for_unknown_task(self) -> None:
        self.assertEqual(self.client.get("/api/voice/draft/nope").status_code, 404)
        self.assertEqual(
            self.client.post("/api/voice/draft/nope/export", json={}).status_code,
            404,
        )

    def test_files_serving_with_traversal_guard(self) -> None:
        project_dir = self.tmp / "files_project"
        project_dir.mkdir()
        secret = self.tmp / "secret.txt"
        secret.write_text("top secret", encoding="utf-8")
        public = project_dir / "result.txt"
        public.write_text("hello", encoding="utf-8")

        record = task_registry.create("files-test")
        record.result = mock.Mock(project_dir=project_dir)

        response = self.client.get(f"/api/files/task/{record.task_id}/result.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "hello")

        # Traversal attempt resolves outside the project dir.
        response = self.client.get(f"/api/files/task/{record.task_id}/../secret.txt")
        self.assertIn(response.status_code, (400, 404))

        # Unknown task.
        response = self.client.get("/api/files/task/nope/x.txt")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
