from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import AppConfig, load_app_config, save_app_config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_config_round_trip_preserves_user_preferences(self) -> None:
        config = AppConfig(
            output_dir=r"D:\Videos\Galaxy",
            tts_engine="sapi",
            voice_name="Vietnamese Voice",
            rate=3,
            volume=85,
            pause_ms=400,
            max_chars=180,
            export_mp3=False,
            keep_segments=False,
            video_export_wav=True,
            video_export_mp3=False,
            video_source_language="en",
            video_target_language="vi",
            whisper_model="small",
            ai_provider="deepseek",
            ai_model="deepseek-v4-flash",
            ai_base_url="https://api.deepseek.com",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_app_config(config, path)

            self.assertEqual(load_app_config(path), config)

    def test_invalid_config_values_fall_back_or_are_clamped(self) -> None:
        payload = {
            "tts_engine": "unknown",
            "rate": 999,
            "volume": -5,
            "pause_ms": "bad",
            "max_chars": 9999,
            "export_mp3": "yes",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            config = load_app_config(path)

        self.assertEqual(config.tts_engine, "edge")
        self.assertEqual(config.rate, 10)
        self.assertEqual(config.volume, 0)
        self.assertEqual(config.pause_ms, 250)
        self.assertEqual(config.max_chars, 260)
        self.assertTrue(config.export_mp3)

    def test_broken_json_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("{broken", encoding="utf-8")

            self.assertEqual(load_app_config(path), AppConfig())
            self.assertFalse(path.exists())
            self.assertEqual(len(list(path.parent.glob("config.json.invalid-*"))), 1)

    def test_invalid_utf8_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_bytes(b'\xff{"output_dir": "exports"}')

            self.assertEqual(load_app_config(path), AppConfig())
            self.assertFalse(path.exists())
            self.assertEqual(len(list(path.parent.glob("config.json.invalid-*"))), 1)

    def test_valid_json_with_wrong_shape_is_preserved_as_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("[]", encoding="utf-8")

            self.assertEqual(load_app_config(path), AppConfig())
            self.assertFalse(path.exists())
            self.assertEqual(len(list(path.parent.glob("config.json.invalid-*"))), 1)

    def test_read_os_error_is_reported_to_the_caller(self) -> None:
        path = Path("config.json")
        with patch.object(Path, "read_text", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                load_app_config(path)

    def test_api_key_is_never_written_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"output_dir": "exports", "ai_api_key": "secret-key"}),
                encoding="utf-8",
            )
            config = load_app_config(path)
            save_app_config(config, path)
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertNotIn("ai_api_key", saved)


if __name__ == "__main__":
    unittest.main()
