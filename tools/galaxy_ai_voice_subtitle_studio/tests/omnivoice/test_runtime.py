from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock
from unittest.mock import patch

from app.common.errors import TaskCancelledError
from app.omnivoice.runtime import (
    CPU_DEVICE,
    CUDA_DEVICE,
    OmniVoiceRuntime,
    XPU_DEVICE,
    clear_model_cache,
    inspect_runtime,
    inspect_runtime_devices,
    install_omnivoice_runtime,
    load_supported_language_ids,
    normalize_omnivoice_device,
    remove_runtime_engine,
)


class OmniVoiceRuntimeTests(unittest.TestCase):
    def test_direct_installer_cancellation_terminates_captured_process(self) -> None:
        process = mock.Mock()
        process.poll.return_value = None
        stop_event = mock.Mock()
        stop_event.is_set.return_value = False
        stop_event.wait.return_value = True
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = OmniVoiceRuntime.from_base(Path(temp_dir))
            installer = Path(temp_dir) / "install.ps1"
            installer.write_text("Write-Host ok", encoding="utf-8")
            with patch("app.omnivoice.runtime.guard_output_space"), patch(
                "app.omnivoice.runtime.subprocess.Popen", return_value=process
            ), patch(
                "app.omnivoice.runtime.terminate_process_tree"
            ) as terminate, self.assertRaises(TaskCancelledError):
                install_omnivoice_runtime(runtime, installer, stop_event=stop_event)

        terminate.assert_called_once_with(process)

    def test_runtime_layout_keeps_heavy_files_outside_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = OmniVoiceRuntime.from_base(Path(temp_dir))

        self.assertEqual(runtime.root, Path(temp_dir) / "GalaxyAIStudio" / "models" / "OmniVoice")
        self.assertEqual(runtime.python_path, runtime.root / ".venv" / "Scripts" / "python.exe")
        self.assertEqual(runtime.profiles_dir, runtime.root / "voices")
        self.assertEqual(runtime.cache_dir, runtime.root / "cache")
        self.assertEqual(runtime.source_dir, runtime.root / "source")

    def test_missing_python_marks_runtime_as_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            status = inspect_runtime(OmniVoiceRuntime.from_base(Path(temp_dir)))

        self.assertFalse(status.installed)
        self.assertIn("chưa được cài", status.message)

    def test_created_venv_without_completed_install_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = OmniVoiceRuntime.from_base(Path(temp_dir))
            runtime.python_path.parent.mkdir(parents=True)
            runtime.python_path.write_text("partial runtime", encoding="utf-8")

            status = inspect_runtime(runtime)

        self.assertFalse(status.installed)
        self.assertIn("chưa hoàn tất", status.message)

    def test_runtime_with_marker_but_missing_package_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = OmniVoiceRuntime.from_base(Path(temp_dir))
            runtime.python_path.parent.mkdir(parents=True)
            runtime.python_path.write_text("partial runtime", encoding="utf-8")
            runtime.metadata_path.write_text("{}", encoding="utf-8")
            completed = CompletedProcess(
                args=[],
                returncode=1,
                stdout="omnivoice\n",
                stderr="",
            )
            with patch("app.omnivoice.runtime.subprocess.run", return_value=completed):
                status = inspect_runtime(runtime)

        self.assertFalse(status.installed)
        self.assertIn("omnivoice", status.message)

    def test_device_codes_are_normalized(self) -> None:
        self.assertEqual(normalize_omnivoice_device("CUDA"), CUDA_DEVICE)
        self.assertEqual(normalize_omnivoice_device("xpu"), XPU_DEVICE)
        self.assertEqual(normalize_omnivoice_device("CPU"), CPU_DEVICE)
        self.assertEqual(normalize_omnivoice_device("iris"), "auto")

    def test_runtime_devices_come_from_the_isolated_torch_runtime(self) -> None:
        completed = CompletedProcess(args=[], returncode=0, stdout="cuda,cpu\n", stderr="")
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.omnivoice.runtime.subprocess.run", return_value=completed
        ):
            devices = inspect_runtime_devices(OmniVoiceRuntime.from_base(Path(temp_dir)))

        self.assertEqual(devices, (CUDA_DEVICE, CPU_DEVICE))

    def test_runtime_device_probe_falls_back_to_cpu_when_probe_fails(self) -> None:
        completed = CompletedProcess(args=[], returncode=1, stdout="", stderr="broken")
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.omnivoice.runtime.subprocess.run", return_value=completed
        ):
            devices = inspect_runtime_devices(OmniVoiceRuntime.from_base(Path(temp_dir)))

        self.assertEqual(devices, (CPU_DEVICE,))

    def test_runtime_install_is_noninteractive_and_managed_by_task(self) -> None:
        process = mock.Mock()
        process.poll.side_effect = [None, 0]
        process.returncode = 0
        status = mock.Mock(installed=True, python_path=Path("python.exe"), message="ready")
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = OmniVoiceRuntime.from_base(Path(temp_dir))
            installer = Path(temp_dir) / "install.ps1"
            installer.write_text("Write-Host ok", encoding="utf-8")
            with mock.patch("app.omnivoice.runtime.guard_output_space") as guard, mock.patch(
                "app.omnivoice.runtime.subprocess.Popen", return_value=process
            ) as popen, mock.patch(
                "app.omnivoice.runtime.inspect_runtime", return_value=status
            ), mock.patch(
                "app.omnivoice.runtime.managed_media_processes.add"
            ) as add, mock.patch(
                "app.omnivoice.runtime.managed_media_processes.discard"
            ) as discard:
                result = install_omnivoice_runtime(
                    runtime, installer, device="cpu", task_id="install-1"
                )

        guard.assert_called_once_with(runtime.root, minimum_mib=5 * 1024)
        command = popen.call_args.args[0]
        self.assertIn("-NonInteractive", command)
        add.assert_called_once_with(process, task_id="install-1")
        discard.assert_called_once_with(process)
        self.assertEqual(result["message"], "ready")

    def test_workspace_language_map_exposes_the_full_model_language_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            language_ids = load_supported_language_ids(
                OmniVoiceRuntime.from_base(Path(temp_dir))
            )

        self.assertGreaterEqual(len(language_ids), 647)
        self.assertIn("vi", language_ids)
        self.assertEqual(language_ids[-1], "auto")

    def test_removing_runtime_preserves_voice_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = OmniVoiceRuntime.from_base(Path(temp_dir))
            runtime.python_path.parent.mkdir(parents=True)
            runtime.python_path.write_text("python", encoding="utf-8")
            runtime.models_dir.mkdir(parents=True)
            runtime.cache_dir.mkdir(parents=True)
            runtime.profiles_dir.mkdir(parents=True)
            runtime.source_dir.mkdir(parents=True)
            profile = runtime.profiles_dir / "narrator.pt"
            profile.write_bytes(b"voice")

            remove_runtime_engine(runtime)

            self.assertTrue(profile.is_file())
            self.assertFalse(runtime.python_path.exists())
            self.assertFalse(runtime.cache_dir.exists())
            self.assertFalse(runtime.source_dir.exists())

    def test_clearing_model_cache_recreates_empty_cache_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = OmniVoiceRuntime.from_base(Path(temp_dir))
            runtime.cache_dir.mkdir(parents=True)
            (runtime.cache_dir / "model.bin").write_bytes(b"model")

            clear_model_cache(runtime)

            self.assertEqual(list(runtime.cache_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
