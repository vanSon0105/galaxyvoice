from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.omnivoice.profiles import finalize_voice_profile, prepare_voice_profile
from app.server.main import create_app
from app.server.routers import voice_library as library_router


class VoiceLibraryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="galaxy_voice_library_")
        self.root = Path(self.temp.name)
        self.config_path = self.root / "config.json"
        self.profiles_dir = self.root / "profiles"
        self.library_dir = self.root / "library"
        self.client = TestClient(create_app(config_path=self.config_path))
        self.runtime_patch = mock.patch.object(library_router, "_profiles_dir", return_value=self.profiles_dir)
        self.data_patch = mock.patch.object(library_router, "_library_dir", return_value=self.library_dir)
        self.system_patch = mock.patch.object(library_router, "_system_voices", return_value=[])
        self.runtime_patch.start()
        self.data_patch.start()
        self.system_patch.start()

    def tearDown(self) -> None:
        self.system_patch.stop()
        self.data_patch.stop()
        self.runtime_patch.stop()
        self.client.close()
        self.temp.cleanup()

    def _legacy_profile(self, name: str = "Son") -> str:
        pending = prepare_voice_profile(self.profiles_dir, name)
        pending.prompt_path.write_bytes(b"voice-prompt")
        profile = finalize_voice_profile(
            pending,
            display_name=name,
            language="vi",
            reference_audio=None,
            reference_text="Xin chao",
            consent_confirmed=True,
            consent_basis="owner",
            consent_statement="Test fixture voice",
        )
        return profile.profile_id

    def test_existing_profile_is_visible_and_metadata_can_be_updated(self) -> None:
        profile_id = self._legacy_profile()
        listed = self.client.get("/api/voice-library/voices")
        self.assertEqual(listed.status_code, 200, listed.text)
        voice = listed.json()[0]
        self.assertEqual(voice["voice_id"], f"omnivoice:{profile_id}")
        self.assertEqual(voice["source"], "cloned")

        updated = self.client.patch(
            f"/api/voice-library/voices/omnivoice:{profile_id}",
            json={"tags": ["review", "nam"], "notes": "Giong kenh chinh", "favorite": True},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["tags"], ["review", "nam"])
        self.assertTrue(updated.json()["favorite"])

    def test_clone_import_requires_consent_and_copies_reference(self) -> None:
        audio = self.root / "sample.wav"
        audio.write_bytes(b"RIFFsample")
        rejected = self.client.post(
            "/api/voice-library/voices/import-audio",
            json={"name": "My clone", "source": "cloned", "audio_path": str(audio)},
        )
        self.assertEqual(rejected.status_code, 422)

        created = self.client.post(
            "/api/voice-library/voices/import-audio",
            json={
                "name": "My clone",
                "source": "cloned",
                "language": "vi",
                "audio_path": str(audio),
                "reference_text": "Xin chao",
                "consent": {"confirmed": True, "basis": "owner", "statement": "My voice"},
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        voice = created.json()
        self.assertTrue(voice["preview_available"])
        self.assertEqual(voice["selection"]["source"], "reference")
        preview = self.client.get(f"/api/voice-library/voices/{voice['voice_id']}/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.content, b"RIFFsample")

    def test_design_bundle_roundtrip_and_project_pin(self) -> None:
        created = self.client.post(
            "/api/voice-library/voices/design",
            json={"name": "Warm narrator", "language": "vi", "instruction": "am ap, cham rai"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        voice = created.json()

        exported = self.client.post(
            f"/api/voice-library/voices/{voice['voice_id']}/export",
            json={"output_path": str(self.root / "warm.galaxyvoice")},
        )
        self.assertEqual(exported.status_code, 200, exported.text)
        bundle_path = Path(exported.json()["path"])
        with zipfile.ZipFile(bundle_path) as archive:
            manifest = json.loads(archive.read("voice.json"))
        self.assertEqual(manifest["format"], "galaxy.voice-profile")
        self.assertEqual(manifest["voice"]["source"], "designed")

        pinned = self.client.post(
            f"/api/voice-library/voices/{voice['voice_id']}/pin",
            json={"project_id": "project-1"},
        )
        self.assertEqual(pinned.status_code, 200, pinned.text)
        self.assertEqual(pinned.json()["project_id"], "project-1")
        self.assertTrue(Path(pinned.json()["snapshot_path"]).is_file())
        graph = self.client.get("/api/project-graph/projects/project-1").json()
        library = next(node for node in graph["nodes"] if node["workspace"] == "library")
        self.assertEqual(library["owner_id"], f"project-1:{voice['voice_id']}")
        self.assertEqual(library["assets"][0]["ownership"], "managed")

        second_pin = self.client.post(
            f"/api/voice-library/voices/{voice['voice_id']}/pin",
            json={"project_id": "project-2"},
        )
        self.assertEqual(second_pin.status_code, 200, second_pin.text)
        second_graph = self.client.get("/api/project-graph/projects/project-2").json()
        second_library = next(
            node for node in second_graph["nodes"] if node["workspace"] == "library"
        )
        self.assertEqual(second_library["owner_id"], f"project-2:{voice['voice_id']}")

        deleted = self.client.delete(f"/api/voice-library/voices/{voice['voice_id']}")
        self.assertEqual(deleted.status_code, 409)
        forced = self.client.delete(f"/api/voice-library/voices/{voice['voice_id']}?force=true")
        self.assertEqual(forced.status_code, 200)

        imported = self.client.post(
            "/api/voice-library/import",
            json={"bundle_path": str(bundle_path)},
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(imported.json()["source"], "designed")

    def test_clone_bundle_reinstalls_a_portable_prompt_profile(self) -> None:
        profile_id = self._legacy_profile("Portable Son")
        voice_id = f"omnivoice:{profile_id}"
        bundle = self.root / "portable.galaxyvoice"

        exported = self.client.post(
            f"/api/voice-library/voices/{voice_id}/export",
            json={"output_path": str(bundle)},
        )
        self.assertEqual(exported.status_code, 200, exported.text)

        imported = self.client.post(
            "/api/voice-library/import",
            json={"bundle_path": str(bundle)},
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        restored = imported.json()
        self.assertEqual(restored["selection"]["source"], "profile")
        self.assertNotEqual(restored["selection"]["profile_id"], profile_id)
        restored_dir = self.profiles_dir / restored["selection"]["profile_id"]
        self.assertTrue((restored_dir / "voice.pt").is_file())
        self.assertTrue((restored_dir / "profile.json").is_file())

    def test_stable_sample_keeps_a_saved_prompt_profile_selectable(self) -> None:
        profile_id = self._legacy_profile("Stable Son")
        sample = self.root / "stable.wav"
        sample.write_bytes(b"RIFFstable")
        voice_id = f"omnivoice:{profile_id}"

        updated = self.client.post(
            f"/api/voice-library/voices/{voice_id}/stable-sample",
            json={"audio_path": str(sample), "reference_text": "Xin chao"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["selection"]["source"], "profile")

        listed = self.client.get("/api/voice-library/voices").json()
        restored = next(item for item in listed if item["voice_id"] == voice_id)
        self.assertEqual(restored["selection"]["source"], "profile")
        self.assertTrue(restored["preview_available"])

    def test_bundle_rejects_unsafe_archive_paths(self) -> None:
        bundle = self.root / "unsafe.galaxyvoice"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("../escape.txt", "bad")
            archive.writestr("voice.json", "{}")
        response = self.client.post("/api/voice-library/import", json={"bundle_path": str(bundle)})
        self.assertEqual(response.status_code, 422)
        self.assertFalse((self.root / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
