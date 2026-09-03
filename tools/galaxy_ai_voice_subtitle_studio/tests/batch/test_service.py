from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.batch.models import BatchItemSpec, BatchSpec
from app.batch.repository import BatchRepository
from app.batch.service import BatchService
from app.studio.models import StudioArtifact, StudioGenerationSpec


class _CountingRepository(BatchRepository):
    def __init__(self, index_path: Path) -> None:
        super().__init__(index_path)
        self.save_calls = 0

    def save(self, run) -> None:
        self.save_calls += 1
        super().save(run)


class _ParallelEngine:
    engine_id = "sapi"
    max_parallelism = 8

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.prewarm_calls = 0
        self.lock = threading.Lock()

    def prewarm(self, _spec: StudioGenerationSpec, _progress=None) -> None:
        self.prewarm_calls += 1

    def generate(self, spec: StudioGenerationSpec, progress=None) -> StudioArtifact:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.04)
            project_dir = Path(spec.output_dir) / spec.output_name
            project_dir.mkdir(parents=True)
            wav_path = project_dir / "voice.wav"
            wav_path.write_bytes(b"wav")
            manifest_path = project_dir / "manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            return StudioArtifact(project_dir, wav_path, None, manifest_path)
        finally:
            with self.lock:
                self.active -= 1


class BatchServiceThroughputTests(unittest.TestCase):
    def test_parallel_batch_prewarms_and_coalesces_manifest_writes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="galaxy_batch_throughput_") as temp_dir:
            root = Path(temp_dir)
            repository = _CountingRepository(root / "runs.json")
            run = repository.create(
                BatchSpec(
                    project_id="project-1",
                    title="Parallel batch",
                    output_dir=str(root / "outputs"),
                    engine_id="sapi",
                    formats=("wav",),
                    max_workers=3,
                ),
                tuple(BatchItemSpec(f"item-{index}", f"Line {index}") for index in range(1, 7)),
            )
            checkpoints = []
            engine = _ParallelEngine()

            result = BatchService(
                repository,
                persistence_interval_seconds=60,
            ).execute(
                run.batch_id,
                engine,
                task_id="task-1",
                checkpoint=checkpoints.append,
            )

            self.assertEqual(result.completed_count, 6)
            self.assertEqual(engine.max_active, 3)
            self.assertEqual(engine.prewarm_calls, 1)
            self.assertEqual(repository.save_calls, 2)
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(checkpoints[0]["completed"], 6)


if __name__ == "__main__":
    unittest.main()
