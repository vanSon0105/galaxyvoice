from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from app.voicestudio.runtime import VoiceStudioRuntime, VoiceStudioRuntimeStatus
from app.voicestudio.service import VoiceStudioController


def ready_status(runtime: VoiceStudioRuntime, *, online: bool = False) -> VoiceStudioRuntimeStatus:
    return VoiceStudioRuntimeStatus(
        snapshot_present=True,
        runtime_installed=True,
        webview_installed=True,
        backend_online=online,
        update_required=False,
        version="0.4.2",
        license_id="AGPL-3.0-only",
        python_path=runtime.python_path,
        source_dir=runtime.source_dir,
        missing_components=(),
        message="ready",
    )


class VoiceStudioControllerTests(unittest.TestCase):
    def runtime(self, root: Path) -> VoiceStudioRuntime:
        return VoiceStudioRuntime.from_repository(
            root,
            environ={"VOICESTUDIO_RUNTIME_ROOT": str(root / "managed")},
        )

    def test_launch_starts_managed_uvicorn_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self.runtime(Path(temp_dir))
            runtime.ensure_directories()
            controller = VoiceStudioController(runtime)
            process = Mock()
            process.poll.return_value = None
            with (
                patch(
                    "app.voicestudio.service.inspect_runtime",
                    return_value=ready_status(runtime),
                ),
                patch("app.voicestudio.service.subprocess.Popen", return_value=process) as popen,
                patch("app.voicestudio.service.managed_media_processes.add") as register,
            ):
                mode = controller.launch()

        self.assertEqual(mode, "local")
        command = popen.call_args.args[0]
        self.assertEqual(command[:3], [str(runtime.python_path), "-m", "uvicorn"])
        self.assertIn(str(runtime.source_dir / "backend"), command)
        self.assertEqual(
            popen.call_args.kwargs["env"]["OMNIVOICE_PROJECT_ROOT"],
            str(runtime.source_dir),
        )
        self.assertEqual(
            popen.call_args.kwargs["env"]["OMNIVOICE_ANALYTICS_DISABLED"],
            "1",
        )
        register.assert_called_once_with(process)

    def test_launch_attaches_to_an_existing_local_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self.runtime(Path(temp_dir))
            controller = VoiceStudioController(runtime)
            with (
                patch(
                    "app.voicestudio.service.inspect_runtime",
                    return_value=ready_status(runtime, online=True),
                ),
                patch("app.voicestudio.service.frontend_available", return_value=True),
                patch("app.voicestudio.service.subprocess.Popen") as popen,
            ):
                mode = controller.launch()

        self.assertEqual(mode, "attached")
        popen.assert_not_called()

    def test_wait_until_ready_requires_backend_and_production_frontend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = VoiceStudioController(self.runtime(Path(temp_dir)))
            with (
                patch("app.voicestudio.service.backend_available", return_value=True),
                patch("app.voicestudio.service.frontend_available", return_value=True),
            ):
                self.assertTrue(controller.wait_until_ready(timeout=0.1, poll_interval=0.01))

    def test_launch_without_local_runtime_has_an_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self.runtime(Path(temp_dir))
            unavailable = VoiceStudioRuntimeStatus(
                snapshot_present=True,
                runtime_installed=False,
                webview_installed=False,
                backend_online=False,
                update_required=False,
                version="0.4.2",
                license_id="AGPL-3.0-only",
                python_path=runtime.python_path,
                source_dir=runtime.source_dir,
                missing_components=("Python runtime", "WebView bridge"),
                message="missing",
            )
            controller = VoiceStudioController(runtime)
            with patch("app.voicestudio.service.inspect_runtime", return_value=unavailable):
                with self.assertRaisesRegex(RuntimeError, "Cài runtime local"):
                    controller.launch()

    def test_installer_receives_snapshot_and_managed_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = self.runtime(root)
            runtime.installer_path.parent.mkdir(parents=True, exist_ok=True)
            runtime.installer_path.write_text("", encoding="utf-8")
            runtime.snapshot_dir.mkdir(parents=True)
            runtime.snapshot_metadata_path.write_text("{}", encoding="utf-8")
            runtime.webview_wheel.parent.mkdir(parents=True)
            runtime.webview_wheel.write_bytes(b"wheel")
            controller = VoiceStudioController(runtime)
            process = Mock()
            process.poll.return_value = None
            with (
                patch("app.voicestudio.service.subprocess.Popen", return_value=process) as popen,
                patch("app.voicestudio.service.managed_media_processes.add"),
            ):
                controller.run_installer()

        command = popen.call_args.args[0]
        self.assertIn(str(runtime.snapshot_dir), command)
        self.assertIn(str(runtime.root), command)

    def test_installer_log_tail_returns_the_latest_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = self.runtime(Path(temp_dir))
            runtime.ensure_directories()
            runtime.installer_log_path.write_text(
                "old output\nPython launcher failed\n",
                encoding="utf-8",
            )
            controller = VoiceStudioController(runtime)

            detail = controller.installer_log_tail(max_chars=24)

        self.assertIn("launcher failed", detail)

    def test_disable_upstream_analytics_records_an_explicit_opt_out(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = VoiceStudioController(self.runtime(Path(temp_dir)))
            response = MagicMock()
            response.status = 200
            response.__enter__.return_value = response
            with patch("app.voicestudio.service.urlopen", return_value=response) as open_url:
                controller.disable_upstream_analytics()

        request = open_url.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:3900/api/settings/analytics",
        )
        self.assertEqual(json.loads(request.data), {"enabled": False})


if __name__ == "__main__":
    unittest.main()
