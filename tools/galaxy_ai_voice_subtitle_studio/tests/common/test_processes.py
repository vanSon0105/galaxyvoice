from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.processes import ManagedProcessRegistry  # noqa: E402


class ProcessRegistryTests(unittest.TestCase):
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

        with patch("app.processes.subprocess.run") as run:
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
