from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.audio_separation.service import (
    AudioSeparationResult,
    DownloadableAudioModel,
    UVRModel,
)
from app.common.errors import TaskCancelledError
from app.server.main import create_app
from app.server.routers import audio_separation as audio_router
from app.server.tasks import CANCELLED, DONE, task_registry


def _wait_status(task_id: str, timeout: float = 3.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = task_registry.get(task_id)
        if record is not None and record.status != "running":
            return record.status
        time.sleep(0.02)
    raise AssertionError(f"Task {task_id} did not finish")


class AudioSeparationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="galaxy_audio_api_")
        self.root = Path(self._temp.name)
        self.config_path = self.root / "config.json"
        self.client = TestClient(create_app(config_path=self.config_path))
        task_registry._tasks.clear()
        audio_router.reset_audio_api_caches()

    def tearDown(self) -> None:
        self.client.close()
        self._temp.cleanup()

    def test_meta_and_models_expose_uvr_controls(self) -> None:
        model = UVRModel("mdx", "Kim Vocal 2", "Kim_Vocal_2.onnx", self.root)
        with mock.patch.object(audio_router, "discover_uvr_models", return_value=(model,)):
            meta = self.client.get("/api/audio/meta")
            models = self.client.get("/api/audio/models")

        self.assertEqual(meta.status_code, 200)
        self.assertEqual(
            {item["code"] for item in meta.json()["methods"]},
            {"mdx", "mdxc", "vr", "demucs"},
        )
        self.assertIn("mdx", meta.json()["method_controls"])
        self.assertEqual(models.json()[0]["filename"], "Kim_Vocal_2.onnx")

    def test_model_discovery_is_cached_until_refresh(self) -> None:
        with mock.patch.object(audio_router, "discover_uvr_models", return_value=()) as discover:
            self.client.get("/api/audio/models")
            self.client.get("/api/audio/models")
            self.client.get("/api/audio/models", params={"refresh": True})
        self.assertEqual(discover.call_count, 2)

    def test_model_catalog_exposes_install_state(self) -> None:
        catalog = (
            DownloadableAudioModel(
                filename="Kim_Vocal_2.onnx",
                name="Kim Vocal 2",
                model_type="MDX",
                method="mdx",
                stems=("vocals", "instrumental"),
            ),
        )
        installed = (UVRModel("mdx", "Kim Vocal 2", "Kim_Vocal_2.onnx", self.root),)
        with (
            mock.patch.object(audio_router, "list_downloadable_audio_models", return_value=catalog),
            mock.patch.object(audio_router, "discover_uvr_models", return_value=installed),
        ):
            response = self.client.get("/api/audio/models/catalog")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()[0]["installed"])

    def test_model_download_runs_as_a_task(self) -> None:
        catalog_model = DownloadableAudioModel(
            filename="melband_roformer.ckpt",
            name="MelBand RoFormer",
            model_type="MDXC",
            method="mdxc",
            stems=("vocals", "instrumental"),
        )
        with (
            mock.patch.object(
                audio_router,
                "list_downloadable_audio_models",
                return_value=(catalog_model,),
            ),
            mock.patch.object(audio_router, "download_audio_model", return_value=self.root / "model"),
        ):
            response = self.client.post(
                "/api/audio/models/download",
                json={"filename": catalog_model.filename},
            )
            task_id = response.json()["task_id"]
            self.assertEqual(_wait_status(task_id), DONE)

        self.assertEqual(task_registry.get(task_id).result.name, "model")

    def test_custom_presets_can_be_saved_and_deleted(self) -> None:
        response = self.client.post(
            "/api/audio/presets",
            json={
                "name": "Podcast",
                "settings": {
                    "method": "vr",
                    "model_filename": "UVR-DeNoise-Lite.pth",
                    "sample_mode": True,
                    "ignored": "value",
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        presets = self.client.get("/api/audio/presets").json()
        self.assertEqual(presets["custom"]["Podcast"]["method"], "vr")
        self.assertNotIn("ignored", presets["custom"]["Podcast"])

        deleted = self.client.delete("/api/audio/presets/Podcast")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/audio/presets").json()["custom"], {})

    def test_runtime_probe_returns_checking_without_blocking_request(self) -> None:
        release = threading.Event()

        def slow_probe(*_args):
            release.wait(1)
            return True, "ready"

        with (
            mock.patch.object(audio_router, "resolve_audio_device", return_value="cpu"),
            mock.patch.object(audio_router, "audio_separator_runtime_ready", side_effect=slow_probe),
        ):
            started = time.monotonic()
            response = self.client.get("/api/audio/runtime", params={"device": "cpu"})
            elapsed = time.monotonic() - started
            self.assertEqual(response.json()["state"], "checking")
            self.assertLess(elapsed, 0.5)
            release.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                ready = self.client.get("/api/audio/runtime", params={"device": "cpu"}).json()
                if ready["state"] == "ready":
                    break
                time.sleep(0.02)
            self.assertTrue(ready["ready"])

    def test_separation_task_returns_playable_stem_urls(self) -> None:
        source = self.root / "song.wav"
        source.write_bytes(b"RIFF")

        def fake_separate(options, **_kwargs):
            project = self.root / "result"
            project.mkdir(exist_ok=True)
            vocal = project / "song_vocals.wav"
            vocal.write_bytes(b"RIFF")
            manifest = project / "audio_separation_manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            return AudioSeparationResult(project, (vocal,), manifest, ())

        with mock.patch("app.audio_separation.service.separate_audio", side_effect=fake_separate):
            response = self.client.post(
                "/api/audio/separate",
                json={
                    "input_path": str(source),
                    "output_dir": str(self.root),
                    "model_filename": "Kim_Vocal_2.onnx",
                },
            )
            task_id = response.json()["task_id"]
            self.assertEqual(_wait_status(task_id), DONE)

        record = task_registry.get(task_id)
        self.assertIsNotNone(record)
        self.assertEqual(record.result.output_paths[0].name, "song_vocals.wav")
        served = self.client.get(f"/api/files/task/{task_id}/song_vocals.wav")
        self.assertEqual(served.status_code, 200)

    def test_cancel_terminates_only_processes_owned_by_audio_task(self) -> None:
        source = self.root / "song.wav"
        source.write_bytes(b"RIFF")

        def wait_for_cancel(_options, *, stop_event, **_kwargs):
            stop_event.wait(2)
            raise TaskCancelledError()

        with (
            mock.patch("app.audio_separation.service.separate_audio", side_effect=wait_for_cancel),
            mock.patch.object(audio_router.managed_media_processes, "terminate_task") as terminate,
        ):
            response = self.client.post(
                "/api/audio/separate",
                json={"input_path": str(source), "output_dir": str(self.root)},
            )
            task_id = response.json()["task_id"]
            cancelled = self.client.post(f"/api/tasks/{task_id}/cancel")
            self.assertEqual(cancelled.status_code, 200)
            self.assertEqual(_wait_status(task_id), CANCELLED)
            terminate.assert_called_once_with(task_id)


if __name__ == "__main__":
    unittest.main()
