from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.runtime.jobs import (
    DONE,
    INTERRUPTED,
    PAUSED,
    RUNNING,
    JobStore,
    TaskRegistry,
)
from app.runtime.resources import ResourceScheduler


class PersistentJobRunnerTests(unittest.TestCase):
    def test_job_reports_progress_and_persists_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            events: list[dict[str, object]] = []
            store = JobStore(Path(temp_dir) / "jobs.json")
            registry = TaskRegistry(store=store, event_sink=events.append)
            record = registry.create(
                "transcribe",
                capability_id="asr.faster-whisper",
                resumable=True,
                project_id="project-1",
                workflow_id="workflow-1",
            )

            def operation(context):
                context.report("halfway", progress=0.5)
                context.save_checkpoint({"segment": 12})
                return {"ok": True}

            registry.submit(record, operation, lambda result: result)
            self.assertEqual(registry.wait_for_running(2), [])

            finished = registry.get(record.task_id)
            self.assertEqual(finished.status, DONE)
            self.assertEqual(finished.progress, 1.0)
            self.assertEqual(finished.checkpoint, {"segment": 12})
            self.assertTrue(any(event.get("type") == "progress" for event in events))

            restored = TaskRegistry(store=store)
            snapshot = restored.get(record.task_id)
            self.assertEqual(snapshot.status, DONE)
            self.assertEqual(snapshot.checkpoint, {"segment": 12})
            self.assertIsNone(snapshot.result)

    def test_restart_pauses_resumable_work_and_interrupts_other_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobStore(Path(temp_dir) / "jobs.json")
            registry = TaskRegistry(store=store)
            resumable = registry.create("longform", resumable=True)
            ordinary = registry.create("translate", resumable=False)
            registry.save_checkpoint(resumable.task_id, {"span": 4})

            restored = TaskRegistry(store=store)

            self.assertEqual(restored.get(resumable.task_id).status, PAUSED)
            self.assertEqual(restored.get(resumable.task_id).checkpoint, {"span": 4})
            self.assertEqual(restored.get(ordinary.task_id).status, INTERRUPTED)

    def test_checkpoint_does_not_persist_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobStore(Path(temp_dir) / "jobs.json")
            registry = TaskRegistry(store=store)
            record = registry.create("secure", resumable=True)
            registry.save_checkpoint(
                record.task_id,
                {
                    "segment": 4,
                    "api_key": "sk-secret",
                    "nested": {"authorization": "Bearer secret", "offset": 12},
                },
            )

            restored = TaskRegistry(store=store).get(record.task_id)
            self.assertEqual(
                restored.checkpoint,
                {"segment": 4, "nested": {"offset": 12}},
            )

    def test_resource_keys_serialize_jobs(self) -> None:
        scheduler = ResourceScheduler({"accelerator": 1})
        registry = TaskRegistry(scheduler=scheduler)
        first = registry.create("first", resource_keys=("accelerator",))
        second = registry.create("second", resource_keys=("accelerator",))
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()

        registry.submit(
            first,
            lambda _context: first_entered.set() or release_first.wait(2),
        )
        self.assertTrue(first_entered.wait(1))
        registry.submit(second, lambda _context: second_entered.set())
        time.sleep(0.05)
        self.assertFalse(second_entered.is_set())
        release_first.set()
        self.assertEqual(registry.wait_for_running(2), [])
        self.assertTrue(second_entered.is_set())

    def test_live_pause_and_resume_are_cooperative(self) -> None:
        registry = TaskRegistry()
        record = registry.create("longform", resumable=True, pausable=True)
        started = threading.Event()
        passed_pause = threading.Event()

        def operation(context):
            started.set()
            while not passed_pause.is_set():
                context.wait_if_paused()
                time.sleep(0.01)
            return True

        registry.submit(record, operation)
        self.assertTrue(started.wait(1))
        self.assertTrue(registry.pause(record.task_id))
        self.assertEqual(registry.get(record.task_id).status, PAUSED)
        self.assertTrue(registry.resume(record.task_id))
        self.assertEqual(registry.get(record.task_id).status, RUNNING)
        passed_pause.set()
        self.assertEqual(registry.wait_for_running(2), [])
        self.assertEqual(registry.get(record.task_id).status, DONE)

    def test_job_paused_while_queued_stays_paused_after_acquiring_resource(self) -> None:
        scheduler = ResourceScheduler({"accelerator": 1})
        holder_entered = threading.Event()
        release_holder = threading.Event()
        operation_entered = threading.Event()

        def hold_resource() -> None:
            with scheduler.acquire("holder", ("accelerator",), threading.Event()):
                holder_entered.set()
                release_holder.wait(2)

        holder = threading.Thread(target=hold_resource)
        holder.start()
        self.assertTrue(holder_entered.wait(1))

        registry = TaskRegistry(scheduler=scheduler)
        record = registry.create(
            "queued-pause",
            resumable=True,
            pausable=True,
            resource_keys=("accelerator",),
        )
        registry.submit(record, lambda _context: operation_entered.set())
        deadline = time.monotonic() + 1
        while registry.get(record.task_id).status != "queued" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(registry.pause(record.task_id))

        release_holder.set()
        holder.join(1)
        time.sleep(0.05)
        self.assertEqual(registry.get(record.task_id).status, PAUSED)
        self.assertFalse(operation_entered.is_set())

        self.assertTrue(registry.resume(record.task_id))
        self.assertEqual(registry.wait_for_running(2), [])
        self.assertTrue(operation_entered.is_set())


if __name__ == "__main__":
    unittest.main()
