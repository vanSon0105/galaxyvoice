"""Phase-0 spike tests: web server foundation (no pywebview needed)."""
from __future__ import annotations

import asyncio
import threading
import time
import unittest

from fastapi.testclient import TestClient

from app.server.event_bus import EventBus, event_bus
from app.server.main import create_app, health_ping_age, record_health_ping
from app.server.tasks import CANCELLED, DONE, FAILED, TaskRegistry, run_task, task_registry


class EventBusTests(unittest.TestCase):
    def test_emit_from_worker_thread_delivers_in_order(self) -> None:
        async def scenario() -> list[dict]:
            bus = EventBus()
            loop = asyncio.get_running_loop()
            bus.bind_loop(loop)
            queue = bus.subscribe()

            def emit_all() -> None:
                for index in range(1, 4):
                    bus.emit({"type": "progress", "index": index})

            thread = threading.Thread(target=emit_all)
            thread.start()
            thread.join()

            received = []
            for _ in range(3):
                received.append(await asyncio.wait_for(queue.get(), timeout=2.0))
            return received

        received = asyncio.run(scenario())
        self.assertEqual(
            [message["index"] for message in received],
            [1, 2, 3],
        )

    def test_slow_consumer_drops_oldest_not_newest(self) -> None:
        async def scenario() -> None:
            bus = EventBus()
            bus.bind_loop(asyncio.get_running_loop())
            queue = bus.subscribe()
            for index in range(300):
                bus._deliver(queue, {"type": "progress", "index": index})
            self.assertEqual(queue.qsize(), 256)
            last = None
            while not queue.empty():
                last = queue.get_nowait()
            self.assertEqual(last["index"], 299)

        asyncio.run(scenario())


class TaskRegistryTests(unittest.TestCase):
    def test_cancel_sets_stop_event_only_while_running(self) -> None:
        registry = TaskRegistry()
        record = registry.create("spike")
        self.assertTrue(registry.cancel(record.task_id))
        self.assertTrue(record.stop_event.is_set())
        registry.finish(record.task_id, status=DONE, result={"ok": True})
        self.assertFalse(registry.cancel(record.task_id))

    def test_finish_records_status_and_result(self) -> None:
        registry = TaskRegistry()
        record = registry.create("spike")
        registry.finish(record.task_id, status=CANCELLED)
        self.assertEqual(registry.get(record.task_id).status, CANCELLED)
        self.assertEqual(registry.running_count(), 0)

    def test_cancel_all_invokes_hooks_and_waits_for_threads(self) -> None:
        registry = TaskRegistry()
        record = registry.create("spike")
        stopped = threading.Event()
        record.on_cancel = stopped.set
        thread = threading.Thread(target=lambda: stopped.wait(1), daemon=True)
        record.thread = thread
        thread.start()

        registry.cancel_all()

        self.assertTrue(record.stop_event.is_set())
        self.assertTrue(stopped.is_set())
        self.assertEqual(registry.wait_for_running(1), [])

    def test_run_task_reports_serializer_errors_as_failed(self) -> None:
        record = task_registry.create("serializer-error")
        run_task(record, lambda: {"ok": True}, lambda _result: 1 / 0)
        deadline = time.monotonic() + 2
        while record.status == "running" and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(record.status, FAILED)
        self.assertIn("division by zero", record.error or "")

    def test_cancelled_task_cannot_be_overwritten_by_late_success(self) -> None:
        record = task_registry.create("late-success")
        release = threading.Event()
        run_task(record, lambda: release.wait(1) or {"ok": True})

        self.assertTrue(task_registry.cancel(record.task_id))
        release.set()
        self.assertEqual(task_registry.wait_for_running(2), [])
        self.assertEqual(record.status, CANCELLED)
        self.assertIsNone(record.result)


class ServerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

    def tearDown(self) -> None:
        record_health_ping()

    def test_health_returns_ok_and_records_ping(self) -> None:
        record_health_ping()
        self.assertLess(health_ping_age(), 2.0)
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("running_tasks", body)
        self.assertLess(health_ping_age(), 2.0)

    def test_websocket_receives_progress_and_task_events_in_order(self) -> None:
        with self.client.websocket_connect("/ws/events") as websocket:
            # Reset shared state so this test is deterministic.
            task_registry._tasks.clear()

            def emit_sequence() -> None:
                event_bus.emit({"type": "progress", "task_id": "t1", "message": "a"})
                event_bus.emit({"type": "progress", "task_id": "t1", "message": "b"})
                event_bus.emit({"type": "task", "task_id": "t1", "status": DONE})

            thread = threading.Thread(target=emit_sequence)
            thread.start()
            thread.join()

            first = websocket.receive_json()
            second = websocket.receive_json()
            third = websocket.receive_json()
            self.assertEqual(first["message"], "a")
            self.assertEqual(second["message"], "b")
            self.assertEqual(third["status"], DONE)

    def test_cancel_unknown_task_returns_404(self) -> None:
        response = self.client.post("/api/tasks/nope_missing/cancel")
        self.assertEqual(response.status_code, 404)

    def test_root_serves_built_frontend(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Galaxy AI Voice", response.text)


if __name__ == "__main__":
    unittest.main()
