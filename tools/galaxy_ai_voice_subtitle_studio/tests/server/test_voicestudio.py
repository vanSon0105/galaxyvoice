from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.server.event_bus import event_bus
from app.server.routers import voicestudio
from app.server.tasks import DONE, task_registry
from app.voicestudio.runtime import VoiceStudioRuntime, VoiceStudioRuntimeStatus


def ready_status(runtime: VoiceStudioRuntime) -> VoiceStudioRuntimeStatus:
    return VoiceStudioRuntimeStatus(
        snapshot_present=True,
        runtime_installed=True,
        backend_online=False,
        update_required=False,
        version="0.4.2",
        license_id="AGPL-3.0-only",
        python_path=runtime.python_path,
        source_dir=runtime.source_dir,
        missing_components=(),
        message="ready",
    )


class VoiceStudioRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        voicestudio.shutdown_voicestudio()

    def tearDown(self) -> None:
        voicestudio.shutdown_voicestudio()

    def runtime(self, root: Path) -> VoiceStudioRuntime:
        return VoiceStudioRuntime.from_repository(
            root,
            environ={"VOICESTUDIO_RUNTIME_ROOT": str(root / "managed")},
        )

    def test_status_uses_lightweight_runtime_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self.runtime(Path(temp_dir))
            controller = Mock(runtime=runtime)
            controller.is_running.return_value = True
            with (
                patch.object(voicestudio, "_get_controller", return_value=controller),
                patch.object(
                    voicestudio,
                    "inspect_runtime",
                    return_value=ready_status(runtime),
                ) as inspect,
            ):
                response = voicestudio.status()

        inspect.assert_called_once_with(runtime, probe_backend=False)
        self.assertTrue(response.backend_online)
        self.assertEqual(response.backend_url, runtime.backend_url)

    def test_launch_waits_until_frontend_is_ready(self) -> None:
        runtime = Mock(backend_url="http://127.0.0.1:3900")
        controller = Mock(runtime=runtime)
        controller.launch.return_value = "local"
        controller.wait_until_ready.return_value = True
        with patch.object(voicestudio, "_get_controller", return_value=controller):
            response = voicestudio.launch()

        self.assertEqual(response.result, "local")
        controller.wait_until_ready.assert_called_once_with()
        controller.disable_upstream_analytics.assert_called_once_with()

    def test_launch_timeout_stops_backend_started_by_galaxy(self) -> None:
        runtime = Mock(backend_url="http://127.0.0.1:3900")
        controller = Mock(runtime=runtime)
        controller.launch.return_value = "local"
        controller.wait_until_ready.return_value = False
        controller.backend_log_tail.return_value = "startup failed"
        with (
            patch.object(voicestudio, "_get_controller", return_value=controller),
            self.assertRaises(HTTPException) as raised,
        ):
            voicestudio.launch()

        self.assertEqual(raised.exception.status_code, 503)
        controller.stop.assert_called_once_with()

    def test_install_task_reaches_done_and_emits_installed_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self.runtime(Path(temp_dir))
            runtime.snapshot_dir.mkdir(parents=True)
            runtime.snapshot_metadata_path.write_text("{}", encoding="utf-8")
            process = Mock(returncode=0)
            process.poll.side_effect = [None, 0]
            controller = Mock(runtime=runtime)
            controller.installer_running.return_value = False
            controller.run_installer.return_value = process
            controller.installer_log_tail.return_value = "Installing local runtime"
            emitted: list[dict[str, object]] = []
            with (
                patch.object(voicestudio, "_get_controller", return_value=controller),
                patch.object(event_bus, "emit", side_effect=emitted.append),
            ):
                response = voicestudio.install(voicestudio.InstallRequest())
                record = task_registry.get(response["task_id"])
                deadline = time.monotonic() + 2
                while record is not None and record.status != DONE and time.monotonic() < deadline:
                    time.sleep(0.01)

        self.assertIsNotNone(record)
        self.assertEqual(record.status, DONE)
        self.assertEqual(record.result, {"success": True})
        self.assertIn("Installing local runtime", record.logs)
        self.assertTrue(
            any(event.get("kind") == "voicestudio_installed" for event in emitted)
        )
        controller.finish_installer.assert_called_once_with(process)


if __name__ == "__main__":
    unittest.main()
