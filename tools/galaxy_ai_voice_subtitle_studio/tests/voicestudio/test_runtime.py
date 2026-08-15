from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.voicestudio.runtime import (
    DEFAULT_FRONTEND_URL,
    VOICESTUDIO_LICENSE,
    VoiceStudioRuntime,
    inspect_runtime,
)


class VoiceStudioRuntimeTests(unittest.TestCase):
    def test_frontend_url_matches_the_voicestudio_vite_and_tauri_port(self) -> None:
        self.assertEqual(DEFAULT_FRONTEND_URL, "http://127.0.0.1:3901")

    def test_runtime_reads_the_real_voicestudio_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir)
            frontend = repository / "omnivoicestudio" / "frontend"
            frontend.mkdir(parents=True)
            (frontend / "package.json").write_text(
                json.dumps(
                    {
                        "name": "omnivoice-studio",
                        "version": "0.4.2",
                        "license": VOICESTUDIO_LICENSE,
                    }
                ),
                encoding="utf-8",
            )
            runtime = VoiceStudioRuntime.from_repository(repository, environ={})

            status = inspect_runtime(runtime, probe_backend=False)

        self.assertTrue(status.source_present)
        self.assertEqual(status.version, "0.4.2")
        self.assertEqual(status.license_id, VOICESTUDIO_LICENSE)
        self.assertFalse(status.installed)

    def test_environment_override_finds_an_installed_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = root / "VoiceStudio.exe"
            executable.write_bytes(b"exe")
            runtime = VoiceStudioRuntime.from_repository(
                root,
                environ={"VOICESTUDIO_EXECUTABLE": str(executable)},
            )

            status = inspect_runtime(runtime, probe_backend=False)

        self.assertTrue(status.installed)
        self.assertEqual(status.executable, executable)
        self.assertEqual(status.launch_mode, "installed")

    def test_source_mode_requires_bun_and_uv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir)
            source = repository / "omnivoicestudio"
            (source / "frontend").mkdir(parents=True)
            (source / "frontend" / "package.json").write_text(
                json.dumps({"version": "0.4.2", "license": VOICESTUDIO_LICENSE}),
                encoding="utf-8",
            )
            runtime = VoiceStudioRuntime.from_repository(repository, environ={})

            with patch("app.voicestudio.runtime.shutil.which", return_value=None):
                status = inspect_runtime(runtime, probe_backend=False)

        self.assertFalse(status.source_ready)
        self.assertIn("Bun", status.missing_tools)
        self.assertIn("uv", status.missing_tools)

    def test_backend_probe_is_reported_without_changing_install_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = VoiceStudioRuntime.from_repository(Path(temp_dir), environ={})
            with patch("app.voicestudio.runtime.backend_available", return_value=True):
                status = inspect_runtime(runtime, probe_backend=True)

        self.assertTrue(status.backend_online)
        self.assertFalse(status.installed)


if __name__ == "__main__":
    unittest.main()
