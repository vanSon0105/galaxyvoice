"""Native Studio API acceptance tests (the TTS engine is replaced at its adapter seam)."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.omnivoice.models import OmniVoiceResult
from app.server.main import create_app
from app.server.routers import studio as studio_router
from app.server.tasks import DONE, task_registry


def _wait_done(task_id: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = task_registry.get(task_id)
        if record is not None and record.status == DONE:
            return
        if record is not None and record.error:
            raise AssertionError(record.error)
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish in time")


def _result(root: Path, name: str = "take") -> OmniVoiceResult:
    project_dir = root / name
    project_dir.mkdir(parents=True, exist_ok=True)
    wav_path = project_dir / "voice.wav"
    wav_path.write_bytes(b"RIFFstudio")
    mp3_path = project_dir / "voice.mp3"
    mp3_path.write_bytes(b"ID3studio")
    manifest_path = project_dir / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    return OmniVoiceResult(project_dir, wav_path, mp3_path, manifest_path)


class StudioApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="galaxy_test_studio_")
        self.root = Path(self._tmp.name)
        self.config_path = self.root / "config.json"
        self.client = TestClient(create_app(config_path=self.config_path))
        task_registry._tasks.clear()
        self.worker_patcher = mock.patch.object(studio_router, "_worker_client")
        self.worker_patcher.start().return_value = mock.Mock()
        self.generate_patcher = mock.patch(
            "app.studio.omnivoice_adapter.generate_omnivoice_audio",
            side_effect=lambda options, client, progress=None: _result(
                self.root, options.project_name
            ),
        )
        self.generate_patcher.start()

    def tearDown(self) -> None:
        self.generate_patcher.stop()
        self.worker_patcher.stop()
        self.client.close()
        self._tmp.cleanup()

    def _generate(
        self, title: str = "Bản đọc 1", formats: list[str] | None = None
    ) -> dict[str, object]:
        response = self.client.post(
            "/api/studio/generations",
            json={
                "project_id": "project-1",
                "title": title,
                "text": "Xin chào Galaxy",
                "language": "vi",
                "output_dir": str(self.root),
                "output_name": title,
                "voice": {"source": "auto"},
                "formats": formats or ["wav", "mp3"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        _wait_done(task_id)
        return task_registry.get(task_id).result

    def test_generation_is_persisted_and_audio_is_available_by_take_id(self) -> None:
        result = self._generate()
        take = result["take"]

        history = self.client.get("/api/studio/takes?project_id=project-1")
        self.assertEqual(history.status_code, 200)
        self.assertEqual([item["take_id"] for item in history.json()], [take["take_id"]])
        self.assertEqual(history.json()[0]["engine_id"], "omnivoice")

        audio = self.client.get(f"/api/studio/takes/{take['take_id']}/audio?format=wav")
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.content, b"RIFFstudio")

        graph = self.client.get("/api/project-graph/projects/project-1").json()
        studio = next(node for node in graph["nodes"] if node["workspace"] == "studio")
        self.assertEqual(studio["owner_id"], take["take_id"])
        self.assertIn("voice_wav", {asset["role"] for asset in studio["assets"]})

        restarted = TestClient(create_app(config_path=self.config_path))
        try:
            persisted = restarted.get("/api/studio/takes?project_id=project-1").json()
            self.assertEqual(persisted[0]["title"], "Bản đọc 1")
        finally:
            restarted.close()

    def test_project_has_one_primary_take_and_saved_take_can_be_rerun(self) -> None:
        first = self._generate("A")["take"]
        second = self._generate("B")["take"]

        promoted = self.client.patch(
            f"/api/studio/takes/{first['take_id']}/primary", json={"primary": True}
        )
        self.assertEqual(promoted.status_code, 200)
        self.client.patch(
            f"/api/studio/takes/{second['take_id']}/primary", json={"primary": True}
        )
        takes = self.client.get("/api/studio/takes?project_id=project-1").json()
        primary_ids = [item["take_id"] for item in takes if item["primary"]]
        self.assertEqual(primary_ids, [second["take_id"]])

        rerun = self.client.post(f"/api/studio/takes/{first['take_id']}/rerun")
        self.assertEqual(rerun.status_code, 200, rerun.text)
        _wait_done(rerun.json()["task_id"])
        rerun_take = task_registry.get(rerun.json()["task_id"]).result["take"]
        self.assertNotEqual(rerun_take["take_id"], first["take_id"])
        self.assertEqual(rerun_take["rerun_of"], first["take_id"])

    def test_generation_rejects_empty_text(self) -> None:
        response = self.client.post(
            "/api/studio/generations",
            json={"title": "Trống", "text": " ", "voice": {"source": "auto"}},
        )
        self.assertEqual(response.status_code, 422)

    def test_generation_requires_project_and_only_exports_requested_formats(self) -> None:
        missing_project = self.client.post(
            "/api/studio/generations",
            json={"title": "Không dự án", "text": "Xin chào", "voice": {"source": "auto"}},
        )
        self.assertEqual(missing_project.status_code, 422)

        take = self._generate("Chỉ WAV", ["wav"])["take"]
        unavailable = self.client.get(
            f"/api/studio/takes/{take['take_id']}/audio?format=mp3"
        )
        self.assertEqual(unavailable.status_code, 404)

    def test_saving_a_cloned_profile_requires_consent(self) -> None:
        reference = self.root / "reference.wav"
        reference.write_bytes(b"RIFFreference")
        payload = {
            "project_id": "project-1",
            "title": "Clone",
            "text": "Xin chào",
            "output_dir": str(self.root),
            "voice": {
                "source": "reference",
                "reference_audio": str(reference),
                "save_profile_name": "My clone",
            },
        }
        rejected = self.client.post("/api/studio/generations", json=payload)
        self.assertEqual(rejected.status_code, 422)

        payload["voice"]["consent_confirmed"] = True
        accepted = self.client.post("/api/studio/generations", json=payload)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        _wait_done(accepted.json()["task_id"])


if __name__ == "__main__":
    unittest.main()
