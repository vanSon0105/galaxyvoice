from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from app.common.processes import managed_media_processes
from app.omnivoice.client import OmniVoiceWorkerClient
from app.omnivoice.runtime import OmniVoiceRuntime, OmniVoiceRuntimeStatus


class OmniVoiceWorkerClientTests(unittest.TestCase):
    def test_worker_stays_alive_across_requests_and_reports_progress(self) -> None:
        managed_media_processes.reset()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            worker = root / "worker.py"
            worker.write_text(
                textwrap.dedent(
                    """
                    import json
                    import os
                    import sys

                    for raw in sys.stdin:
                        request = json.loads(raw)
                        base = {
                            "protocol_version": 1,
                            "request_id": request["request_id"],
                        }
                        print(json.dumps({**base, "type": "progress", "payload": {"message": "working"}}), flush=True)
                        print(json.dumps({**base, "type": "result", "payload": {"pid": os.getpid(), "path": os.environ["PATH"], "python_utf8": os.environ.get("PYTHONUTF8"), "python_io_encoding": os.environ.get("PYTHONIOENCODING")}}), flush=True)
                    """
                ),
                encoding="utf-8",
            )
            runtime_root = root / "runtime"
            runtime = OmniVoiceRuntime(
                root=runtime_root,
                python_path=Path(sys.executable),
                models_dir=runtime_root / "checkpoints",
                profiles_dir=runtime_root / "voices",
                cache_dir=runtime_root / "cache",
            )
            progress: list[str] = []
            client = OmniVoiceWorkerClient(runtime, worker)
            studio = root / "studio"
            bundled_bin = studio / "bin"
            bundled_bin.mkdir(parents=True)
            try:
                ready = OmniVoiceRuntimeStatus(
                    installed=True,
                    message="ready",
                    python_path=runtime.python_path,
                )
                with (
                    patch("app.omnivoice.client.inspect_runtime", return_value=ready),
                    patch("app.omnivoice.client.studio_root", return_value=studio),
                ):
                    first = client.request("ping", {}, on_progress=progress.append)
                    second = client.request("ping", {}, on_progress=progress.append)
            finally:
                client.close()

        self.assertEqual(first["pid"], second["pid"])
        self.assertTrue(str(first["path"]).startswith(str(bundled_bin)))
        self.assertEqual(first["python_utf8"], "1")
        self.assertEqual(first["python_io_encoding"], "utf-8")
        self.assertEqual(progress, ["working", "working"])
        self.assertFalse(client.is_running)


if __name__ == "__main__":
    unittest.main()
