"""OmniVoice router tests with monkeypatched services (no real venv/torch)."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.omnivoice.batch import OmniVoiceBatchItem, OmniVoiceBatchResult
from app.omnivoice.models import OmniVoiceResult
from app.omnivoice.runtime import OmniVoiceRuntime
from app.server.main import create_app
from app.server.routers import omnivoice as omnivoice_router
from app.server.tasks import DONE, FAILED, task_registry


def _wait_status(task_id: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = task_registry.get(task_id)
        if record is not None and record.status != "running":
            return record.status
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish in time")


def _make_result(tmp: Path) -> OmniVoiceResult:
    project_dir = tmp / "omnivoice_project"
    project_dir.mkdir()
    wav = project_dir / "voice.wav"
    wav.write_bytes(b"RIFF")
    manifest = project_dir / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    return OmniVoiceResult(
        project_dir=project_dir,
        wav_path=wav,
        mp3_path=None,
        manifest_path=manifest,
        profile_id="profile-1",
        warnings=(),
    )


class OmniVoiceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="galaxy_test_omnivoice_")
        self.tmp = Path(self._tmp.name)
        self.client = TestClient(create_app(config_path=self.tmp / "config.json"))
        task_registry._tasks.clear()
        self._runtime_patcher = mock.patch.object(
            omnivoice_router,
            "_runtime",
            return_value=OmniVoiceRuntime.from_base(self.tmp),
        )
        self._runtime_patcher.start()
        self._client_patcher = mock.patch.object(omnivoice_router, "_worker_client")
        self.fake_client = self._client_patcher.start()
        self.fake_client.return_value = mock.Mock()

    def tearDown(self) -> None:
        self._client_patcher.stop()
        self._runtime_patcher.stop()
        self.client.close()
        self._tmp.cleanup()

    def test_status_reports_not_installed_runtime(self) -> None:
        response = self.client.get("/api/omnivoice/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["installed"])
        self.assertIn("languages", body)
        self.assertIn("vi", body["languages"])

    def test_generate_requires_text(self) -> None:
        response = self.client.post("/api/omnivoice/generate", json={"text": "  "})
        self.assertEqual(response.status_code, 422)

    def test_generate_task_runs_and_serializes_result(self) -> None:
        from app.omnivoice.service import generate_omnivoice_audio

        with mock.patch.object(
            omnivoice_router,
            "generate_omnivoice_audio",
            side_effect=lambda options, client, progress=None: (
                progress("đang tạo"),
                _make_result(self.tmp),
            )[1],
        ):
            response = self.client.post(
                "/api/omnivoice/generate",
                json={"text": "Xin chào", "output_dir": str(self.tmp)},
            )
            self.assertEqual(response.status_code, 200)
            task_id = response.json()["task_id"]
            self.assertEqual(_wait_status(task_id), DONE)
            payload = task_registry.get(task_id).result
            self.assertEqual(payload.project_dir.name, "omnivoice_project")

    def test_generate_task_cancel_calls_client_stop(self) -> None:
        from app.omnivoice.service import generate_omnivoice_audio

        def slow_generate(options, client, progress=None):
            time.sleep(5)
            return _make_result(self.tmp)

        with mock.patch.object(omnivoice_router, "generate_omnivoice_audio", side_effect=slow_generate):
            response = self.client.post(
                "/api/omnivoice/generate",
                json={"text": "Xin chào", "output_dir": str(self.tmp)},
            )
            task_id = response.json()["task_id"]
            record = task_registry.get(task_id)
            self.assertIsNotNone(record.on_cancel)
            cancel = self.client.post(f"/api/tasks/{task_id}/cancel")
            self.assertEqual(cancel.status_code, 200)
            self.fake_client.return_value.stop.assert_called_once()
            record.status = "failed"  # the real thread keeps sleeping; end it

    def test_batch_parses_and_runs(self) -> None:
        from app.omnivoice.batch import generate_omnivoice_batch

        with mock.patch.object(
            omnivoice_router,
            "generate_omnivoice_batch",
            side_effect=lambda base, items, client, combine=False, gap_ms=250, progress=None, stop_event=None: (
                progress("mục 1/1"),
                OmniVoiceBatchResult(
                    project_dir=self.tmp / "batch",
                    manifest_path=self.tmp / "batch" / "manifest.json",
                    item_results=(),
                    combined_wav_path=None,
                    combined_mp3_path=None,
                    warnings=(),
                ),
            )[1],
        ):
            response = self.client.post(
                "/api/omnivoice/batch",
                json={"source": "dòng một\ndòng hai", "output_dir": str(self.tmp)},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(_wait_status(response.json()["task_id"]), DONE)

    def test_batch_rejects_empty_source(self) -> None:
        response = self.client.post(
            "/api/omnivoice/batch",
            json={"source": "   ", "output_dir": str(self.tmp)},
        )
        self.assertEqual(response.status_code, 422)

    def test_profiles_list_and_delete(self) -> None:
        from app.omnivoice.profiles import prepare_voice_profile, finalize_voice_profile

        runtime = omnivoice_router._runtime()
        pending = prepare_voice_profile(runtime.profiles_dir, "Giọng thử")
        (pending.prompt_path).write_bytes(b"fake")
        finalize_voice_profile(
            pending,
            display_name="Giọng thử",
            language="vi",
            reference_audio=None,
            reference_text="Xin chào",
        )
        response = self.client.get("/api/omnivoice/profiles")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["display_name"], "Giọng thử")

        deleted = self.client.delete(f"/api/omnivoice/profiles/{body[0]['profile_id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/omnivoice/profiles").json(), [])

    def test_delete_unknown_profile_returns_404(self) -> None:
        response = self.client.delete("/api/omnivoice/profiles/khong-ton-tai")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
