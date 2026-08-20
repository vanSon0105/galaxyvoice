from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.common.processes import ManagedProcessRegistry  # noqa: E402


class ProcessRegistryTests(unittest.TestCase):
    def test_terminate_task_only_stops_processes_owned_by_that_task(self) -> None:
        class FakeProcess:
            def __init__(self, pid: int) -> None:
                self.pid = pid

            def poll(self):
                return None

        registry = ManagedProcessRegistry()
        first = FakeProcess(101)
        second = FakeProcess(202)
        unowned = FakeProcess(303)
        registry.add(first, task_id="task-a")
        registry.add(second, task_id="task-b")
        registry.add(unowned)

        with patch("app.common.processes.terminate_process_tree") as terminate:
            registry.terminate_task("task-a")

        terminate.assert_called_once_with(first)
        self.assertEqual(
            {item["pid"]: item["task_id"] for item in registry.snapshot()},
            {101: "task-a", 202: "task-b", 303: None},
        )

    def test_process_started_after_shutdown_is_stopped_immediately(self) -> None:
        class FakeProcess:
            pid = 456
            terminated = False

            def poll(self):
                return None

            def terminate(self):
                self.terminated = True

        registry = ManagedProcessRegistry()
        registry.terminate_all()
        process = FakeProcess()

        with patch("app.common.processes.subprocess.run") as run:
            registry.add(process)

        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            registry.ensure_running()
        if os.name == "nt":
            self.assertIn("/T", run.call_args.args[0])
        else:
            self.assertTrue(process.terminated)

        registry.reset()
        registry.ensure_running()


if __name__ == "__main__":
    unittest.main()
