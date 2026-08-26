from __future__ import annotations

import threading
import time
import unittest

from app.common.errors import TaskCancelledError
from app.runtime.resources import ResourceScheduler


class ResourceSchedulerTests(unittest.TestCase):
    def test_same_accelerator_jobs_never_overlap(self) -> None:
        scheduler = ResourceScheduler({"accelerator": 1})
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()

        def first() -> None:
            with scheduler.acquire("first", ("accelerator",), threading.Event()):
                first_entered.set()
                release_first.wait(2)

        def second() -> None:
            with scheduler.acquire("second", ("accelerator",), threading.Event()):
                second_entered.set()

        first_thread = threading.Thread(target=first)
        second_thread = threading.Thread(target=second)
        first_thread.start()
        self.assertTrue(first_entered.wait(1))
        second_thread.start()
        time.sleep(0.05)
        self.assertFalse(second_entered.is_set())

        release_first.set()
        first_thread.join(1)
        second_thread.join(1)
        self.assertTrue(second_entered.is_set())

    def test_disjoint_resources_can_run_together(self) -> None:
        scheduler = ResourceScheduler({"gpu:nvidia": 1, "network": 1})
        gpu_entered = threading.Event()
        network_entered = threading.Event()
        release = threading.Event()

        def run(task_id: str, resource: str, entered: threading.Event) -> None:
            with scheduler.acquire(task_id, (resource,), threading.Event()):
                entered.set()
                release.wait(1)

        gpu_thread = threading.Thread(target=run, args=("gpu", "gpu:nvidia", gpu_entered))
        network_thread = threading.Thread(
            target=run,
            args=("network", "network", network_entered),
        )
        gpu_thread.start()
        network_thread.start()
        self.assertTrue(gpu_entered.wait(1))
        self.assertTrue(network_entered.wait(1))
        release.set()
        gpu_thread.join(1)
        network_thread.join(1)

    def test_cancelled_waiter_leaves_queue(self) -> None:
        scheduler = ResourceScheduler({"accelerator": 1})
        holder_release = threading.Event()
        holder_entered = threading.Event()
        stop_event = threading.Event()
        errors: list[BaseException] = []

        def holder() -> None:
            with scheduler.acquire("holder", ("accelerator",), threading.Event()):
                holder_entered.set()
                holder_release.wait(1)

        def waiter() -> None:
            try:
                with scheduler.acquire("waiter", ("accelerator",), stop_event):
                    pass
            except BaseException as error:
                errors.append(error)

        holder_thread = threading.Thread(target=holder)
        waiter_thread = threading.Thread(target=waiter)
        holder_thread.start()
        self.assertTrue(holder_entered.wait(1))
        waiter_thread.start()
        stop_event.set()
        scheduler.wake()
        waiter_thread.join(1)
        holder_release.set()
        holder_thread.join(1)

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], TaskCancelledError)
        self.assertEqual(scheduler.snapshot()["waiting"], [])


if __name__ == "__main__":
    unittest.main()
