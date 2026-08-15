from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.voicestudio.runtime import VoiceStudioRuntime
from app.voicestudio.service import VoiceStudioController


class VoiceStudioControllerTests(unittest.TestCase):
    def test_launch_prefers_the_installed_desktop_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = root / "VoiceStudio.exe"
            executable.write_bytes(b"exe")
            runtime = VoiceStudioRuntime.from_repository(
                root,
                environ={"VOICESTUDIO_EXECUTABLE": str(executable)},
            )
            controller = VoiceStudioController(runtime)
            process = Mock()
            process.poll.return_value = None
            with (
                patch("app.voicestudio.service.subprocess.Popen", return_value=process) as popen,
                patch("app.voicestudio.service.managed_media_processes.add") as register,
            ):
                mode = controller.launch()

        self.assertEqual(mode, "installed")
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], [str(executable)])
        register.assert_called_once_with(process)

    def test_source_launch_uses_the_repository_dev_stack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir)
            source = repository / "omnivoicestudio"
            source.mkdir()
            runtime = VoiceStudioRuntime.from_repository(repository, environ={})
            controller = VoiceStudioController(runtime)
            process = Mock()
            process.poll.return_value = None
            with (
                patch("app.voicestudio.service.shutil.which", side_effect=lambda name: f"C:/{name}.exe"),
                patch("app.voicestudio.service.subprocess.Popen", return_value=process) as popen,
                patch("app.voicestudio.service.managed_media_processes.add"),
            ):
                mode = controller.launch_source()

        self.assertEqual(mode, "source")
        self.assertEqual(popen.call_args.args[0], ["C:/bun.exe", "run", "dev"])
        self.assertEqual(popen.call_args.kwargs["cwd"], str(source))

    def test_repeated_launch_does_not_replace_a_running_desktop_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = root / "VoiceStudio.exe"
            executable.write_bytes(b"exe")
            runtime = VoiceStudioRuntime.from_repository(
                root,
                environ={"VOICESTUDIO_EXECUTABLE": str(executable)},
            )
            controller = VoiceStudioController(runtime)
            running = Mock()
            running.poll.return_value = None
            controller.process = running
            with patch("app.voicestudio.service.subprocess.Popen") as popen:
                mode = controller.launch()

        self.assertEqual(mode, "installed")
        popen.assert_not_called()

    def test_source_readiness_requires_both_backend_and_frontend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = VoiceStudioController(
                VoiceStudioRuntime.from_repository(Path(temp_dir), environ={})
            )
            with (
                patch("app.voicestudio.service.backend_available", return_value=True),
                patch("app.voicestudio.service.frontend_available", return_value=True),
            ):
                self.assertTrue(controller.wait_for_source_ready(timeout=0.1, poll_interval=0.01))

    def test_launch_without_install_or_ready_source_has_an_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = VoiceStudioController(
                VoiceStudioRuntime.from_repository(Path(temp_dir), environ={})
            )
            with patch("app.voicestudio.service.shutil.which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "cài VoiceStudio"):
                    controller.launch()


if __name__ == "__main__":
    unittest.main()
