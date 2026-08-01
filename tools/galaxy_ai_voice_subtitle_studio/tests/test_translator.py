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
    translate_script_text,
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

    def test_translate_cues_retries_a_batch_returned_in_english_instead_of_vietnamese(self) -> None:
        cues = [
            SubtitleCue(index=index, start_ms=index * 1000, end_ms=(index + 1) * 1000, text=f"这是第 {index} 行")
            for index in range(1, 22)
        ]
        batch_sizes: list[int] = []
        large_batch_calls = 0

        def fake_client(messages, _options):
            nonlocal large_batch_calls
            self.assertIn("Target language: Vietnamese (vi)", messages[1]["content"])
            batch_size = messages[1]["content"].count('"index"')
            batch_sizes.append(batch_size)
            if batch_size == 20:
                large_batch_calls += 1
                if large_batch_calls == 1:
                    return json.dumps(
                        {
                            "translations": [
                                f"This is an English translation for subtitle line {index}"
                                for index in range(1, 21)
                            ]
                        }
                    )
                return json.dumps(
                    {"translations": [f"Đây là bản dịch tiếng Việt {index}" for index in range(1, 21)]},
                    ensure_ascii=False,
                )
            return json.dumps({"translations": ["Đây là bản dịch tiếng Việt 21"]}, ensure_ascii=False)

        translated = translate_cues(
            cues,
            AITranslationOptions(
                source_language="auto",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertTrue(all("English translation" not in cue.text for cue in translated))
        self.assertEqual(batch_sizes, [20, 20, 1])

    def test_translate_cues_retries_chinese_returned_instead_of_vietnamese(self) -> None:
        cues = [
            SubtitleCue(
                index=1,
                start_ms=0,
                end_ms=3760,
                text="\u6211\u7684\u4e16\u754c\uff0c\u4f46\u53ea\u80fd\u4f7f\u7528\u4e00\u683c\u7269\u54c1",
            )
        ]
        responses = iter(
            [
                ["\u6211\u7684\u4e16\u754c\uff0c\u4f46\u53ea\u80fd\u4f7f\u7528\u4e00\u683c\u7269\u54c1\u6765\u901a\u5173"],
                ["Th\u1ebf gi\u1edbi c\u1ee7a t\u00f4i, nh\u01b0ng ch\u1ec9 \u0111\u01b0\u1ee3c d\u00f9ng m\u1ed9t \u00f4 v\u1eadt ph\u1ea9m"],
            ]
        )
        call_count = 0

        def fake_client(messages, _options):
            nonlocal call_count
            call_count += 1
            self.assertIn("Target language: Vietnamese (vi)", messages[1]["content"])
            if call_count == 2:
                self.assertIn("previous response was written in Chinese", messages[1]["content"])
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            cues,
            AITranslationOptions(
                source_language="auto",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(
            translated[0].text,
            "Th\u1ebf gi\u1edbi c\u1ee7a t\u00f4i, nh\u01b0ng ch\u1ec9 \u0111\u01b0\u1ee3c d\u00f9ng m\u1ed9t \u00f4 v\u1eadt ph\u1ea9m",
        )
        self.assertEqual(call_count, 2)

    def test_translate_cues_splits_a_large_batch_returned_in_chinese(self) -> None:
        cues = [
            SubtitleCue(
                index=index,
                start_ms=index * 1000,
                end_ms=(index + 1) * 1000,
                text=f"\u8fd9\u662f\u7b2c {index} \u884c\u5b57\u5e55",
            )
            for index in range(1, 21)
        ]
        batch_sizes: list[int] = []

        def fake_client(messages, _options):
            batch_size = messages[1]["content"].count('"index"')
            batch_sizes.append(batch_size)
            if batch_size > 10:
                return json.dumps(
                    {
                        "translations": [
                            f"\u8fd9\u4ecd\u7136\u662f\u7b2c {index} \u884c\u4e2d\u6587\u5b57\u5e55"
                            for index in range(1, batch_size + 1)
                        ]
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "translations": [
                        f"\u0110\u00e2y l\u00e0 b\u1ea3n d\u1ecbch ti\u1ebfng Vi\u1ec7t {index}"
                        for index in range(1, batch_size + 1)
                    ]
                },
                ensure_ascii=False,
            )

        translated = translate_cues(
            cues,
            AITranslationOptions(
                source_language="auto",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(batch_sizes, [20, 10, 10])
        self.assertEqual(len(translated), 20)
        self.assertTrue(all("b\u1ea3n d\u1ecbch ti\u1ebfng Vi\u1ec7t" in cue.text for cue in translated))
        self.assertEqual([cue.index for cue in translated], list(range(1, 21)))

    def test_translate_cues_rejects_a_persistently_wrong_output_language(self) -> None:
        cues = [
            SubtitleCue(index=index, start_ms=index * 1000, end_ms=(index + 1) * 1000, text=f"这是第 {index} 行")
            for index in range(1, 21)
        ]
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps(
                {
                    "translations": [
                        f"This is an English translation for subtitle line {index}"
                        for index in range(1, 21)
                    ]
                }
            )

        with self.assertRaisesRegex(RuntimeError, "English instead of Vietnamese"):
            translate_cues(
                cues,
                AITranslationOptions(
                    source_language="auto",
                    target_language="vi",
                    api_key="test-key",
                    model="test-model",
                ),
                client=fake_client,
            )

        self.assertEqual(call_count, 2)

    def test_translate_cues_rejects_persistently_chinese_output_for_vietnamese(self) -> None:
        cues = [
            SubtitleCue(
                index=1,
                start_ms=0,
                end_ms=3760,
                text="\u6211\u7684\u4e16\u754c\uff0c\u4f46\u53ea\u80fd\u4f7f\u7528\u4e00\u683c\u7269\u54c1",
            )
        ]
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps(
                {"translations": ["\u8fd9\u4ecd\u7136\u662f\u4e00\u53e5\u4e2d\u6587\u5b57\u5e55"]},
                ensure_ascii=False,
            )

        with self.assertRaisesRegex(RuntimeError, "Chinese instead of Vietnamese"):
            translate_cues(
                cues,
                AITranslationOptions(
                    source_language="auto",
                    target_language="vi",
                    api_key="test-key",
                    model="test-model",
                ),
                client=fake_client,
            )

        self.assertEqual(call_count, 2)

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

    def test_translate_script_text_preserves_blank_lines(self) -> None:
        def fake_client(_messages, _options):
            return json.dumps({"translations": ["Xin chao.", "The gioi."]})

        translated = translate_script_text(
            "Hello.\n\nWorld.",
            AITranslationOptions(
                source_language="en",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated, "Xin chao.\n\nThe gioi.")

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
