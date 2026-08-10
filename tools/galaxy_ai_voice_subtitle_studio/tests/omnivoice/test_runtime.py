from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from app.omnivoice.runtime import (
    CPU_DEVICE,
    CUDA_DEVICE,
    OmniVoiceRuntime,
    XPU_DEVICE,
    clear_model_cache,
    inspect_runtime,
    load_supported_language_ids,
    normalize_omnivoice_device,
    remove_runtime_engine,
)


class OmniVoiceRuntimeTests(unittest.TestCase):
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
