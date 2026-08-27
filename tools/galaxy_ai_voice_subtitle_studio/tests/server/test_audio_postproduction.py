from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.server.main import create_app
from app.audio_postproduction.models import AudioExportResult


class AudioPostproductionApiTests(unittest.TestCase):
    def test_waveform_endpoint_returns_bounded_project_waveform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "project" / "voice.wav"
            source.parent.mkdir()
            with wave.open(str(source), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8_000)
                output.writeframes((1_000).to_bytes(2, "little", signed=True) * 8_000)
            client = TestClient(create_app(config_path=root / "config.json"))

            response = client.post(
                "/api/audio-post/waveform",
                json={"source_path": str(source), "project_dir": str(source.parent), "points": 32},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["duration_ms"], 1_000)
            self.assertEqual(len(response.json()["peaks"]), 32)

    def test_waveform_endpoint_rejects_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = TestClient(create_app(config_path=root / "config.json"))
            response = client.post(
                "/api/audio-post/waveform",
                json={"source_path": str(root / "missing.wav"), "project_dir": str(root / "project")},
            )
            self.assertEqual(response.status_code, 422)

    def test_export_endpoint_maps_contract_and_encodes_project_media_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project with space"
            project.mkdir()
            output = project / "exports" / "final.wav"
            output.parent.mkdir()
            output.write_bytes(b"audio")
            manifest = output.parent / "audio_export_manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            service = mock.Mock()
            service.export.return_value = AudioExportResult(
                "a" * 32, project.resolve(), {"wav": output}, manifest
            )
            client = TestClient(create_app(config_path=project / "config.json"))

            with mock.patch(
                "app.server.routers.audio_postproduction._service", return_value=service
            ):
                response = client.post(
                    "/api/audio-post/exports",
                    json={
                        "project_id": "project-1",
                        "workspace": "studio",
                        "project_dir": str(project),
                        "title": "Final",
                        "sources": [{"source_id": "voice", "path": str(output)}],
                        "formats": ["wav"],
                    },
                )

            self.assertEqual(response.status_code, 200)
            mapped = service.export.call_args.args[0]
            self.assertEqual(mapped.project_id, "project-1")
            self.assertEqual(mapped.sources[0].source_id, "voice")
            self.assertIn("project_dir=", response.json()["media_urls"]["wav"])
            self.assertNotIn("project with space", response.json()["media_urls"]["wav"])


if __name__ == "__main__":
    unittest.main()
