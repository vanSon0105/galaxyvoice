from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import Mock

from app.common.errors import TaskCancelledError
from app.omnivoice.task_runner import OmniVoiceTaskCoordinator


class OmniVoiceTaskCoordinatorTests(unittest.TestCase):
    def test_cancelling_queued_task_does_not_stop_active_worker(self) -> None:
        client = Mock()
        coordinator = OmniVoiceTaskCoordinator(lambda: client)
        active_started = threading.Event()
        release_active = threading.Event()
        queued_stop = threading.Event()
        errors: list[Exception] = []

        def active_operation(_client) -> str:
            active_started.set()
            release_active.wait(2)
            return "done"

        active_thread = threading.Thread(
            target=lambda: coordinator.run("active", threading.Event(), active_operation)
        )
        active_thread.start()
        self.assertTrue(active_started.wait(1))

        def run_queued() -> None:
            try:
                coordinator.run("queued", queued_stop, lambda _client: "unexpected")
            except Exception as error:
                errors.append(error)

        queued_thread = threading.Thread(target=run_queued)
        queued_thread.start()
        time.sleep(0.05)
        queued_stop.set()
        coordinator.cancel("queued")

        client.stop.assert_not_called()
        queued_thread.join(0.5)
        self.assertFalse(queued_thread.is_alive())
        release_active.set()
        active_thread.join(1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], TaskCancelledError)

    def test_cancelling_active_task_stops_its_worker(self) -> None:
        client = Mock()
        coordinator = OmniVoiceTaskCoordinator(lambda: client)
        active_started = threading.Event()
        release_active = threading.Event()

        def operation(_client) -> None:
            active_started.set()
            release_active.wait(2)

        thread = threading.Thread(
            target=lambda: coordinator.run("active", threading.Event(), operation)
        )
        thread.start()
        self.assertTrue(active_started.wait(1))

        coordinator.cancel("active")

        client.stop.assert_called_once_with()
        release_active.set()
        thread.join(1)


if __name__ == "__main__":
    unittest.main()
