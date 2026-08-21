"""Settings & system router tests (config CRUD round-trip against a tmp path)."""
from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from fastapi.testclient import TestClient

from app.server.main import create_app


class SettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="galaxy_test_config_")
        self.config_path = Path(self._tmp.name) / "config.json"
        self.client = TestClient(create_app(config_path=self.config_path))

    def tearDown(self) -> None:
        self.client.close()
        self._tmp.cleanup()

    def test_get_settings_returns_defaults_when_no_file(self) -> None:
        response = self.client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["version"], 6)
        self.assertEqual(body["tts_engine"], "edge")
        self.assertNotIn("ai_api_key", body)

    def test_put_settings_partial_update_persists_to_file(self) -> None:
        response = self.client.put("/api/settings", json={"rate": 3, "volume": 80})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rate"], 3)
        self.assertEqual(response.json()["volume"], 80)
        # Other fields keep defaults
        self.assertEqual(response.json()["pause_ms"], 250)

        persisted = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["rate"], 3)
        self.assertEqual(persisted["volume"], 80)

        # A second, unrelated update must not wipe the first one.
        response = self.client.put("/api/settings", json={"max_chars": 200})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rate"], 3)
        self.assertEqual(response.json()["max_chars"], 200)

    def test_put_settings_clamps_out_of_range_values(self) -> None:
        response = self.client.put("/api/settings", json={"rate": 99, "volume": -5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rate"], 10)
        self.assertEqual(response.json()["volume"], 0)

    def test_put_settings_ignores_unknown_and_secret_fields(self) -> None:
        response = self.client.put(
            "/api/settings",
            json={"ai_api_key": "sk-secret", "not_a_field": 1, "volume": 50},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("ai_api_key", body)
        self.assertNotIn("not_a_field", body)
        self.assertEqual(body["volume"], 50)
        persisted = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertNotIn("ai_api_key", persisted)
        self.assertNotIn("not_a_field", persisted)

    def test_put_settings_non_json_body_rejected(self) -> None:
        response = self.client.put("/api/settings", content="not json", headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)

    def test_settings_meta_lists_engines_providers_languages(self) -> None:
        response = self.client.get("/api/settings/meta")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("edge", [engine["code"] for engine in body["tts_engines"]])
        self.assertTrue(body["whisper_models"])
        self.assertTrue(body["translation_providers"])
        self.assertEqual(
            {"openai", "deepseek", "gemini", "groq", "openrouter", "mistral", "xai", "nvidia", "ollama"},
            {provider["code"] for provider in body["translation_providers"]},
        )
        providers = {provider["code"]: provider for provider in body["translation_providers"]}
        self.assertEqual(providers["nvidia"]["label"], "NVIDIA NIM")
        self.assertEqual(
            providers["nvidia"]["default_model"],
            "nvidia/riva-translate-4b-instruct-v2",
        )
        self.assertEqual(
            providers["nvidia"]["api_key_environment_name"],
            "GALAXY_NVIDIA_API_KEY",
        )
        self.assertTrue(
            all(
                provider["api_key_environment_name"].startswith("GALAXY_")
                and provider["api_key_environment_name"].endswith("_API_KEY")
                for provider in body["translation_providers"]
            )
        )
        self.assertIn(("auto", "Auto detect"), [(item["code"], item["label"]) for item in body["source_languages"]])

    def test_settings_meta_reports_environment_key_without_exposing_it(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"DEEPSEEK_API_KEY": "deepseek-secret-value"},
            clear=False,
        ):
            response = self.client.get("/api/settings/meta")

        self.assertEqual(response.status_code, 200)
        providers = {item["code"]: item for item in response.json()["translation_providers"]}
        self.assertTrue(providers["deepseek"]["api_key_configured"])
        self.assertEqual(
            providers["deepseek"]["api_key_environment_name"],
            "GALAXY_DEEPSEEK_API_KEY",
        )
        self.assertNotIn("deepseek-secret-value", response.text)

    def test_save_translation_api_key_uses_provider_galaxy_environment_name(self) -> None:
        with mock.patch(
            "app.server.routers.settings.set_user_environment"
        ) as save_environment:
            response = self.client.post(
                "/api/settings/translation-api-key",
                json={"provider": "deepseek", "api_key": "deepseek-secret-value"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "provider": "deepseek",
                "environment_name": "GALAXY_DEEPSEEK_API_KEY",
                "configured": True,
            },
        )
        save_environment.assert_called_once_with(
            "GALAXY_DEEPSEEK_API_KEY", "deepseek-secret-value"
        )
        self.assertNotIn("deepseek-secret-value", response.text)

    def test_save_translation_api_key_rejects_unknown_provider_and_empty_key(self) -> None:
        unknown = self.client.post(
            "/api/settings/translation-api-key",
            json={"provider": "unknown", "api_key": "secret"},
        )
        empty = self.client.post(
            "/api/settings/translation-api-key",
            json={"provider": "deepseek", "api_key": "   "},
        )

        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(empty.status_code, 400)

    def test_system_processes_returns_snapshot(self) -> None:
        response = self.client.get("/api/system/processes")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsInstance(body["media_processes"], list)
        self.assertEqual(body["running_tasks"], 0)


if __name__ == "__main__":
    unittest.main()
