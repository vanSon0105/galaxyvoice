from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.batch.parser import parse_batch_source
from app.server.main import create_app
from app.server.routers import batch as batch_router
from app.server.tasks import CANCELLED, DONE, FAILED, task_registry
from app.studio.models import StudioArtifact, StudioGenerationSpec


def _wait_terminal(task_id: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = task_registry.get(task_id)
        if record is not None and record.status in {DONE, FAILED, CANCELLED}:
            return record.status
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not finish")


def _wave(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 800)


class BatchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="galaxy_batch_test_")
        self.root = Path(self.temp.name)
        self.client = TestClient(create_app(config_path=self.root / "config.json"))
        task_registry._tasks.clear()
        self.worker = mock.patch.object(batch_router, "_worker_client")
        self.worker.start().return_value = mock.Mock()
        self.attempts: dict[str, int] = {}
        self.fail_once: set[str] = set()
        self.block_first: threading.Event | None = None
        self.release_first: threading.Event | None = None
        self.generator = mock.patch(
            "app.batch.omnivoice_adapter.OmniVoiceBatchAdapter.generate",
            side_effect=self._generate,
        )
        self.generator.start()

    def tearDown(self) -> None:
        self.generator.stop()
        self.worker.stop()
        self.client.close()
        self.temp.cleanup()

    def _generate(self, spec: StudioGenerationSpec, progress=None) -> StudioArtifact:
        count = self.attempts.get(spec.output_name, 0) + 1
        self.attempts[spec.output_name] = count
        if self.block_first and self.release_first and sum(self.attempts.values()) == 1:
            self.block_first.set()
            self.release_first.wait(3)
        if spec.output_name in self.fail_once and count == 1:
            raise RuntimeError("engine item failure")
        project_dir = Path(spec.output_dir) / f"{spec.output_name}-{count}"
        wav_path = project_dir / "voice.wav"
        _wave(wav_path)
        manifest = project_dir / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        return StudioArtifact(project_dir, wav_path, None, manifest)

    def _create(self, items: list[dict[str, object]], **overrides: object) -> dict[str, str]:
        payload: dict[str, object] = {
            "project_id": "project-1",
            "title": "My Batch",
            "output_dir": str(self.root / "outputs"),
            "formats": ["wav"],
            "items": items,
        }
        payload.update(overrides)
        response = self.client.post("/api/batch/runs", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_jsonl_parser_supports_per_item_overrides(self) -> None:
        items = parse_batch_source(
            '{"id":"intro","text":"Xin chào","language":"vi","speed":1.2,'
            '"profile_id":"son","formats":["wav"]}'
        )
        self.assertEqual(items[0].item_id, "intro")
        self.assertEqual(items[0].speed, 1.2)
        self.assertEqual(items[0].profile_id, "son")
        self.assertEqual(items[0].formats, ("wav",))

        duplicate = self.client.post(
            "/api/batch/parse",
            json={"source": '{"id":"a","text":"1"}\n{"id":"a","text":"2"}'},
        )
        self.assertEqual(duplicate.status_code, 422)

        missing_profile = self.client.post(
            "/api/batch/runs",
            json={
                "project_id": "project-1",
                "title": "Invalid voice",
                "output_dir": str(self.root / "outputs"),
                "voice": {"source": "profile"},
                "items": [{"item_id": "one", "text": "Xin chào"}],
            },
        )
        self.assertEqual(missing_profile.status_code, 422)

    def test_partial_success_is_persisted_and_retry_only_runs_failed_items(self) -> None:
        self.fail_once.add("bad")
        started = self._create(
            [
                {"item_id": "good", "text": "Thành công"},
                {"item_id": "bad", "text": "Lỗi lần đầu"},
            ]
        )
        self.assertEqual(_wait_terminal(started["task_id"]), DONE)
        run = self.client.get(f"/api/batch/runs/{started['batch_id']}").json()
        self.assertEqual(run["status"], "partial")
        self.assertEqual(run["completed_count"], 1)
        self.assertEqual(run["failed_count"], 1)

        retried = self.client.post(f"/api/batch/runs/{started['batch_id']}/retry")
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(_wait_terminal(retried.json()["task_id"]), DONE)
        finished = self.client.get(f"/api/batch/runs/{started['batch_id']}").json()
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(self.attempts, {"good": 1, "bad": 2})

        manifest_path = Path(finished["manifest_path"])
        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
        self.assertNotIn("output_dir", manifest["spec"])
        self.assertNotIn(str(self.root), manifest_text)

    def test_combined_output_and_item_audio_are_served_by_ids(self) -> None:
        started = self._create(
            [
                {"item_id": "one", "text": "Một"},
                {"item_id": "two", "text": "Hai"},
            ],
            combine=True,
        )
        self.assertEqual(_wait_terminal(started["task_id"]), DONE)
        combined = self.client.get(f"/api/batch/runs/{started['batch_id']}/audio?format=wav")
        item = self.client.get(
            f"/api/batch/runs/{started['batch_id']}/items/one/audio?format=wav"
        )
        manifest = self.client.get(f"/api/batch/runs/{started['batch_id']}/manifest")
        self.assertEqual(combined.status_code, 200)
        self.assertEqual(item.status_code, 200)
        self.assertEqual(manifest.status_code, 200)

        graph = self.client.get("/api/project-graph/projects/project-1").json()
        batch = next(node for node in graph["nodes"] if node["workspace"] == "batch")
        self.assertEqual(batch["owner_id"], started["batch_id"])
        self.assertIn("combined_wav", {asset["role"] for asset in batch["assets"]})

    def test_cancelled_batch_can_resume_pending_items(self) -> None:
        self.block_first = threading.Event()
        self.release_first = threading.Event()
        started = self._create(
            [
                {"item_id": "one", "text": "Một"},
                {"item_id": "two", "text": "Hai"},
            ]
        )
        self.assertTrue(self.block_first.wait(2))
        cancelled = self.client.post(f"/api/tasks/{started['task_id']}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.release_first.set()
        self.assertEqual(_wait_terminal(started["task_id"]), CANCELLED)

        run = self.client.get(f"/api/batch/runs/{started['batch_id']}").json()
        self.assertEqual(run["status"], "cancelled")
        resumed = self.client.post(f"/api/batch/runs/{started['batch_id']}/resume")
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(_wait_terminal(resumed.json()["task_id"]), DONE)
        finished = self.client.get(f"/api/batch/runs/{started['batch_id']}").json()
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["completed_count"], 2)


if __name__ == "__main__":
    unittest.main()
