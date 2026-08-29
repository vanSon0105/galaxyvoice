from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from app.common.cache import write_json_atomic
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
    def test_progress_persistence_is_throttled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobStore(Path(temp_dir) / "jobs.json")
            with mock.patch.object(store, "save", wraps=store.save) as save:
                registry = TaskRegistry(store=store)
                record = registry.create("chatty")
                before = save.call_count
                for index in range(20):
                    registry.report(record.task_id, f"line {index}", progress=0.5)

                self.assertEqual(save.call_count - before, 1)
                registry.finish(record.task_id, status=DONE)

    def test_throttled_progress_gets_a_trailing_persistence_flush(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobStore(Path(temp_dir) / "jobs.json")
            with mock.patch("app.runtime.jobs.PROGRESS_PERSIST_INTERVAL_SECONDS", 0.05), mock.patch.object(
                store, "save", wraps=store.save
            ) as save:
                registry = TaskRegistry(store=store)
                record = registry.create("chatty")
                registry.report(record.task_id, "first", progress=0.5)
                before = save.call_count
                registry.report(record.task_id, "trailing update")
                self.assertEqual(save.call_count, before)

                deadline = time.monotonic() + 0.5
                while save.call_count == before and time.monotonic() < deadline:
                    time.sleep(0.01)

                self.assertGreater(save.call_count, before)
                restored = TaskRegistry(store=store).get(record.task_id)
                self.assertEqual(restored.message, "trailing update")
                registry.finish(record.task_id, status=DONE)

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
            self.assertEqual(registry.snapshot()[0]["result"], {"ok": True})

            restored = TaskRegistry(store=store)
            snapshot = restored.get(record.task_id)
            self.assertEqual(snapshot.status, DONE)
            self.assertEqual(snapshot.checkpoint, {"segment": 12})
            self.assertIsNone(snapshot.result)

    def test_restart_interrupts_process_bound_work_and_keeps_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobStore(Path(temp_dir) / "jobs.json")
            registry = TaskRegistry(store=store)
            resumable = registry.create("longform", resumable=True)
            ordinary = registry.create("translate", resumable=False)
            registry.save_checkpoint(resumable.task_id, {"span": 4})

            restored = TaskRegistry(store=store)

            self.assertEqual(restored.get(resumable.task_id).status, INTERRUPTED)
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

    def test_restore_redacts_legacy_message_error_and_result_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobStore(Path(temp_dir) / "jobs.json")
            record = TaskRegistry(store=store).create("legacy")
            payload = store.load()[0]
            payload.update({
                "status": DONE,
                "message": "Authorization: Basic dXNlcjpwYXNz",
                "error": "api_key=sk-old",
                "result": {"token": "hf_old", "path": "voice.wav"},
            })
            write_json_atomic(store.path, {"schema_version": 1, "jobs": [payload]})

            restored = TaskRegistry(store=store).get(record.task_id)

            self.assertNotIn("dXNlcjpwYXNz", restored.message)
            self.assertNotIn("sk-old", restored.error)
            self.assertEqual(restored.result_payload, {"path": "voice.wav"})

    def test_progress_log_and_recovery_metadata_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobStore(Path(temp_dir) / "jobs.json")
            registry = TaskRegistry(store=store)
            record = registry.create(
                "longform",
                resumable=True,
                recovery_route="/voice/longform",
                recovery_hint="Mở project và tiếp tục từ checkpoint.",
            )
            registry.report(record.task_id, "Đang dựng chương 2", progress=0.4)

            restored = TaskRegistry(store=store).get(record.task_id)

            self.assertEqual(restored.logs, ["Đang dựng chương 2"])
            self.assertEqual(restored.recovery_route, "/voice/longform")
            self.assertEqual(restored.recovery_hint, "Mở project và tiếp tục từ checkpoint.")

    def test_task_logs_are_bounded_and_secrets_are_redacted(self) -> None:
        registry = TaskRegistry()
        record = registry.create("secure")
        for index in range(140):
            registry.report(
                record.task_id,
                f"line {index} api_key=sk-super-secret",
            )

        snapshot = registry.snapshot()[0]

        self.assertEqual(len(snapshot["logs"]), 100)
        self.assertIn("line 139", snapshot["logs"][-1])
        self.assertNotIn("sk-super-secret", "\n".join(snapshot["logs"]))

    def test_task_logs_redact_quoted_json_credentials(self) -> None:
        registry = TaskRegistry()
        record = registry.create("secure-json")
        registry.report(
            record.task_id,
            '{"api_key":"sk-json", "password": "hidden", "cookie":"session"}',
        )

        line = registry.snapshot()[0]["logs"][0]
        self.assertNotIn("sk-json", line)
        self.assertNotIn("hidden", line)
        self.assertNotIn("session", line)

    def test_serialized_result_redacts_credentials_inside_plain_text_values(self) -> None:
        registry = TaskRegistry()
        record = registry.create("secure-result")
        registry.finish(
            record.task_id,
            status=DONE,
            result_payload={"detail": "Authorization: Bearer sk-result-secret"},
        )

        detail = registry.snapshot()[0]["result"]["detail"]
        self.assertNotIn("sk-result-secret", detail)

    def test_serialized_result_is_redacted_before_websocket_emit(self) -> None:
        events: list[dict[str, object]] = []
        registry = TaskRegistry(event_sink=events.append)
        record = registry.create("secure-result")
        registry.submit(
            record,
            lambda _context: {"detail": "Bearer sk-abcdefghijklmnopqrstuvwxyz"},
            lambda result: result,
        )
        self.assertEqual(registry.wait_for_running(2), [])

        terminal = next(event for event in events if event.get("status") == DONE)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", str(terminal.get("result")))

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
