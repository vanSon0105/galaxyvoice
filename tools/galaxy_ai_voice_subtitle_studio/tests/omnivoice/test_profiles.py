from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.omnivoice.profiles import (
    delete_voice_profile,
    finalize_voice_profile,
    list_voice_profiles,
    prepare_voice_profile,
)


class OmniVoiceProfileTests(unittest.TestCase):
    def test_profile_metadata_can_be_listed_and_deleted_without_torch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles_dir = Path(temp_dir)
            pending = prepare_voice_profile(profiles_dir, "Giọng review nữ")
            pending.prompt_path.write_bytes(b"prompt")
            reference = profiles_dir / "sample.wav"
            reference.write_bytes(b"wave")

            profile = finalize_voice_profile(
                pending,
                display_name="Giọng review nữ",
                language="vi",
                reference_audio=reference,
                reference_text="Xin chào",
            )

            profiles = list_voice_profiles(profiles_dir)
            self.assertEqual(profiles, [profile])
            self.assertTrue(profile.prompt_path.is_file())
            self.assertTrue(profile.reference_audio_path and profile.reference_audio_path.is_file())

            delete_voice_profile(profiles_dir, profile.profile_id)
            self.assertEqual(list_voice_profiles(profiles_dir), [])

    def test_duplicate_profile_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profiles_dir = Path(temp_dir)
            prepare_voice_profile(profiles_dir, "Narrator")
            with self.assertRaises(FileExistsError):
                prepare_voice_profile(profiles_dir, "Narrator")


if __name__ == "__main__":
    unittest.main()
