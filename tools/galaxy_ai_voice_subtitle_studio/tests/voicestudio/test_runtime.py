from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.voicestudio.runtime import (
    DEFAULT_BACKEND_URL,
    VOICESTUDIO_LICENSE,
    VoiceStudioRuntime,
    acquire_webview_profile,
    inspect_runtime,
)


def create_source(source: Path, *, version: str = "0.4.2") -> None:
    (source / "backend").mkdir(parents=True)
    (source / "omnivoice").mkdir(parents=True)
    (source / "frontend" / "dist").mkdir(parents=True)
    (source / "backend" / "main.py").write_text("app = object()", encoding="utf-8")
    (source / "omnivoice" / "__init__.py").write_text("", encoding="utf-8")
    (source / "frontend" / "dist" / "index.html").write_text("<html>", encoding="utf-8")
    (source / "pyproject.toml").write_text(
        f'[project]\nversion = "{version}"\n', encoding="utf-8"
    )
    (source / "LICENSE").write_text("AGPL", encoding="utf-8")


def create_snapshot(repository: Path, *, version: str = "0.4.2") -> Path:
    snapshot = (
        repository
        / "tools"
        / "galaxy_ai_voice_subtitle_studio"
        / "vendor"
        / "voicestudio"
    )
    create_source(snapshot, version=version)
    (snapshot / "SNAPSHOT.json").write_text(
        json.dumps({"version": version, "license": VOICESTUDIO_LICENSE}),
        encoding="utf-8",
    )
    return snapshot


class VoiceStudioRuntimeTests(unittest.TestCase):
    def test_backend_and_frontend_share_the_local_production_url(self) -> None:
        self.assertEqual(DEFAULT_BACKEND_URL, "http://127.0.0.1:3900")

    def test_runtime_uses_vendored_snapshot_and_managed_local_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir)
            snapshot = create_snapshot(repository)
            runtime_root = repository / "managed"

            runtime = VoiceStudioRuntime.from_repository(
                repository,
                environ={"VOICESTUDIO_RUNTIME_ROOT": str(runtime_root)},
            )
            status = inspect_runtime(runtime, probe_backend=False)

        self.assertEqual(runtime.snapshot_dir, snapshot)
        self.assertEqual(runtime.installer_log_path, runtime_root / "logs" / "install.log")
        self.assertEqual(runtime.source_dir, runtime_root / "sources" / "0.4.2")
        self.assertEqual(
            runtime.webview_data_dir,
            runtime_root / "webview" / "profile",
        )
        self.assertTrue(status.snapshot_present)
        self.assertFalse(status.installed)
        self.assertEqual(status.version, "0.4.2")
        self.assertEqual(status.license_id, VOICESTUDIO_LICENSE)

    def test_runtime_is_ready_only_with_python_source_marker_and_webview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir)
            create_snapshot(repository)
            runtime = VoiceStudioRuntime.from_repository(
                repository,
                environ={"VOICESTUDIO_RUNTIME_ROOT": str(repository / "managed")},
            )
            create_source(runtime.source_dir)
            runtime.python_path.parent.mkdir(parents=True)
            runtime.python_path.write_bytes(b"python")
            runtime.metadata_path.write_text(
                json.dumps({"snapshot_version": "0.4.2"}), encoding="utf-8"
            )
            package = runtime.webview_site_packages / "tkwry"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "_core.pyd").write_bytes(b"pyd")

            status = inspect_runtime(runtime, probe_backend=False)

        self.assertTrue(status.runtime_installed)
        self.assertTrue(status.webview_installed)
        self.assertTrue(status.installed)

    def test_snapshot_version_change_requires_runtime_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir)
            create_snapshot(repository, version="0.5.0")
            runtime = VoiceStudioRuntime.from_repository(
                repository,
                environ={"VOICESTUDIO_RUNTIME_ROOT": str(repository / "managed")},
            )
            create_source(runtime.source_dir, version="0.5.0")
            runtime.python_path.parent.mkdir(parents=True)
            runtime.python_path.write_bytes(b"python")
            runtime.metadata_path.write_text(
                json.dumps({"snapshot_version": "0.4.2"}), encoding="utf-8"
            )

            status = inspect_runtime(runtime, probe_backend=False)

        self.assertTrue(status.update_required)
        self.assertFalse(status.installed)

    def test_backend_probe_is_reported_without_changing_install_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = VoiceStudioRuntime.from_repository(
                Path(temp_dir),
                environ={"VOICESTUDIO_RUNTIME_ROOT": str(Path(temp_dir) / "managed")},
            )
            with patch("app.voicestudio.runtime.backend_available", return_value=True):
                status = inspect_runtime(runtime, probe_backend=True)

        self.assertTrue(status.backend_online)
        self.assertFalse(status.installed)

    def test_installer_uses_the_vendored_snapshot_instead_of_a_remote_msi(self) -> None:
        repository = Path(__file__).resolve().parents[4]
        runtime = VoiceStudioRuntime.from_repository(repository)

        script = runtime.installer_path.read_text(encoding="utf-8")

        self.assertIn("SNAPSHOT.json", script)
        self.assertIn("uv sync --frozen", script)
        self.assertIn("tkwry-0.1.4", script)
        self.assertNotIn("api.github.com", script)
        self.assertNotIn("msiexec", script.lower())

    @unittest.skipUnless(sys.platform == "win32", "PowerShell installer is Windows-only")
    def test_installer_skips_an_unavailable_python_launcher_version(self) -> None:
        repository = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = VoiceStudioRuntime.from_repository(
                repository,
                environ={"VOICESTUDIO_RUNTIME_ROOT": temp_dir},
            )
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(runtime.installer_path),
                    "-SnapshotRoot",
                    str(runtime.snapshot_dir),
                    "-RuntimeRoot",
                    str(runtime.root),
                    "-PythonVersionCandidates",
                    "99.99,3.12,3.13",
                    "-ProbePythonOnly",
                    "-NonInteractive",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("PYTHON_RUNTIME=", completed.stdout)

    def test_webview_profile_uses_recovery_directory_while_owner_is_alive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = VoiceStudioRuntime.from_repository(
                Path(temp_dir),
                environ={"VOICESTUDIO_RUNTIME_ROOT": str(Path(temp_dir) / "managed")},
            )
            first = acquire_webview_profile(runtime, process_id=101)
            self.assertEqual(first.owner_path.parent, first.data_directory.parent)
            self.assertNotEqual(first.owner_path.parent, first.data_directory)
            seed = first.data_directory / "EBWebView" / "Local State"
            seed.parent.mkdir(parents=True)
            seed.write_text("warm", encoding="utf-8")
            with patch("app.voicestudio.runtime._process_is_running", return_value=True):
                second = acquire_webview_profile(runtime, process_id=202)

            self.assertFalse(first.recovered)
            self.assertTrue(second.recovered)
            self.assertNotEqual(first.data_directory, second.data_directory)
            self.assertEqual(
                (second.data_directory / "EBWebView" / "Local State").read_text(
                    encoding="utf-8"
                ),
                "warm",
            )
            second.release()
            first.release()

    def test_stale_webview_profile_is_skipped_once_then_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = VoiceStudioRuntime.from_repository(
                Path(temp_dir),
                environ={"VOICESTUDIO_RUNTIME_ROOT": str(Path(temp_dir) / "managed")},
            )
            stale = acquire_webview_profile(runtime, process_id=101)
            with (
                patch("app.voicestudio.runtime._process_is_running", return_value=False),
                patch(
                    "app.voicestudio.runtime._webview_child_is_running",
                    return_value=False,
                ),
            ):
                recovery = acquire_webview_profile(runtime, process_id=202)

            self.assertTrue(recovery.recovered)
            self.assertFalse(stale.owner_path.exists())
            recovery.release()

            fresh = acquire_webview_profile(runtime, process_id=303)
            self.assertFalse(fresh.recovered)
            fresh.release()


if __name__ == "__main__":
    unittest.main()
