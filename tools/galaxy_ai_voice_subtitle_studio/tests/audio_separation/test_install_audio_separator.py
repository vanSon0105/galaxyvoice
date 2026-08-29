from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.audio_separation.service import (  # noqa: E402
    AudioSeparatorRuntime,
    install_audio_separator_runtime,
)
from app.common.errors import TaskCancelledError  # noqa: E402


class AudioSeparatorInstallerTests(unittest.TestCase):
    def test_direct_installer_cancellation_terminates_captured_process(self) -> None:
        process = mock.Mock()
        process.poll.return_value = None
        stop_event = mock.Mock()
        stop_event.is_set.return_value = False
        stop_event.wait.return_value = True
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "runtime"
            runtime = AudioSeparatorRuntime(root / ".venv" / "Scripts" / "python.exe")
            installer = Path(temp_dir) / "install.ps1"
            installer.write_text("Write-Host ok", encoding="utf-8")
            with mock.patch("app.audio_separation.service.guard_output_space"), mock.patch(
                "app.audio_separation.service.subprocess.Popen", return_value=process
            ), mock.patch(
                "app.audio_separation.service.terminate_process_tree"
            ) as terminate, self.assertRaises(TaskCancelledError):
                install_audio_separator_runtime(
                    installer,
                    runtime=runtime,
                    stop_event=stop_event,
                )

        terminate.assert_called_once_with(process)

    def test_runtime_install_is_managed_cancellable_and_logged(self) -> None:
        process = mock.Mock()
        process.poll.side_effect = [None, 0]
        process.returncode = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "runtime"
            runtime = AudioSeparatorRuntime(root / ".venv" / "Scripts" / "python.exe")
            runtime.python_path.parent.mkdir(parents=True)
            runtime.python_path.write_bytes(b"python")
            installer = Path(temp_dir) / "install.ps1"
            installer.write_text("Write-Host ok", encoding="utf-8")
            with mock.patch("app.audio_separation.service.guard_output_space") as guard, mock.patch(
                "app.audio_separation.service.subprocess.Popen", return_value=process
            ) as popen, mock.patch(
                "app.audio_separation.service.managed_media_processes.add"
            ) as add, mock.patch(
                "app.audio_separation.service.managed_media_processes.discard"
            ) as discard:
                result = install_audio_separator_runtime(
                    installer,
                    runtime=runtime,
                    device="cpu",
                    task_id="install-audio-1",
                )

        guard.assert_called_once_with(root, minimum_mib=4 * 1024)
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.STDOUT)
        add.assert_called_once_with(process, task_id="install-audio-1")
        discard.assert_called_once_with(process)
        self.assertEqual(result["python_path"], str(runtime.python_path))

    def test_installer_is_valid_and_pins_the_reviewed_runtime(self) -> None:
        powershell = shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is unavailable.")

        installer = ROOT / "install_audio_separator.ps1"
        content = installer.read_text(encoding="utf-8")
        self.assertIn('$runtimeVersion = "0.44.5"', content)
        self.assertIn('"audio-separator[$extra]==$runtimeVersion"', content)
        self.assertIn("GalaxyAIStudio\\models\\AudioSeparator", content)

        installer_literal = str(installer).replace("'", "''")
        command = f"""
$content = Get-Content -Raw '{installer_literal}'
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseInput(
    $content,
    [ref]$tokens,
    [ref]$errors
) | Out-Null
if ($errors.Count) {{ $errors | Out-String | Write-Error; exit 2 }}
"""
        completed = subprocess.run(
            [powershell, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)


if __name__ == "__main__":
    unittest.main()
