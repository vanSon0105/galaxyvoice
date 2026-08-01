from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.srt import SubtitleCue  # noqa: E402
from app.translator import (  # noqa: E402
    AITranslationOptions,
    default_translation_api_key,
    default_translation_base_url,
    default_translation_model,
    default_translation_provider,
    translate_cues,
    translation_provider_code,
    translation_provider_label,
)


class TranslatorTests(unittest.TestCase):
    def test_translate_cues_preserves_timing_and_order(self) -> None:
        cues = [
            SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hello there."),
            SubtitleCue(index=2, start_ms=1000, end_ms=2000, text="Welcome back."),
        ]

        def fake_client(messages, _options):
            self.assertIn("Hello there.", messages[1]["content"])
            return json.dumps({"translations": ["Xin chao.", "Chao mung quay lai."]})

        translated = translate_cues(
            cues,
            AITranslationOptions(
                source_language="en",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual([cue.text for cue in translated], ["Xin chao.", "Chao mung quay lai."])
        self.assertEqual(translated[0].start_ms, 0)
        self.assertEqual(translated[1].end_ms, 2000)

    def test_translate_cues_can_skip_translation(self) -> None:
        cues = [SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Original")]

        translated = translate_cues(
            cues,
            AITranslationOptions(source_language="en", target_language="none"),
        )

        self.assertIs(translated, cues)

    def test_translate_cues_resolves_provider_defaults(self) -> None:
        cues = [SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hello.")]

        def fake_client(_messages, options):
            self.assertEqual(options.provider, "deepseek")
            self.assertEqual(options.model, "deepseek-v4-flash")
            self.assertEqual(options.base_url, "https://api.deepseek.com")
            return json.dumps({"translations": ["Xin chao."]})

        with patch.dict(os.environ, {}, clear=True):
            with patch("app.env_config._read_windows_environment", return_value=""):
                translated = translate_cues(
                    cues,
                    AITranslationOptions(
                        source_language="en",
                        target_language="vi",
                        provider="deepseek",
                        api_key="test-key",
                    ),
                    client=fake_client,
                )

        self.assertEqual(translated[0].text, "Xin chao.")

    def test_default_translation_api_key_reads_windows_user_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("app.env_config._read_windows_environment", side_effect=lambda name: "user-key" if name == "OPENAI_API_KEY" else ""):
                self.assertEqual(default_translation_api_key(), "user-key")

    def test_deepseek_provider_uses_deepseek_defaults_and_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GALAXY_TRANSLATION_PROVIDER": "deepseek",
                "OPENAI_API_KEY": "openai-key",
                "DEEPSEEK_API_KEY": "deepseek-key",
            },
            clear=True,
        ):
            with patch("app.env_config._read_windows_environment", return_value=""):
                self.assertEqual(default_translation_provider(), "deepseek")
                self.assertEqual(default_translation_api_key("deepseek"), "deepseek-key")
                self.assertEqual(default_translation_model("deepseek"), "deepseek-v4-flash")
                self.assertEqual(default_translation_base_url("deepseek"), "https://api.deepseek.com")

    def test_provider_label_roundtrip_accepts_chatgpt_label(self) -> None:
        label = translation_provider_label("openai")
        self.assertEqual(label, "ChatGPT / OpenAI")
        self.assertEqual(translation_provider_code(label), "openai")


if __name__ == "__main__":
    unittest.main()
