from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.srt import SubtitleCue  # noqa: E402
from app.translator import (  # noqa: E402
    AITranslationOptions,
    _extract_translations,
    _salvage_json_translations,
    default_translation_api_key,
    default_translation_base_url,
    default_translation_model,
    default_translation_provider,
    translate_cues,
    translate_script_text,
    translation_provider_code,
    translation_provider_label,
    validate_translation_options,
)


class TranslatorTests(unittest.TestCase):
    def test_translate_cues_runs_batches_in_parallel_and_preserves_cue_order(self) -> None:
        cues = [
            SubtitleCue(index=index, start_ms=index * 1000, end_ms=(index + 1) * 1000, text=f"Source {index}")
            for index in range(1, 5)
        ]
        first_two_started = threading.Barrier(2)

        def fake_client(messages, _options):
            payload = json.loads(messages[1]["content"].rsplit("\n\n", 1)[-1])
            source_text = payload[0]["text"]
            if source_text in {"Source 1", "Source 2"}:
                first_two_started.wait(timeout=2)
            if source_text == "Source 1":
                time.sleep(0.05)
            return json.dumps({"translations": [f"\u0110\u00e3 d\u1ecbch {source_text}"]}, ensure_ascii=False)

        translated = translate_cues(
            cues,
            AITranslationOptions(
                source_language="en",
                target_language="vi",
                api_key="test-key",
                model="test-model",
                batch_size=1,
                max_workers=2,
            ),
            client=fake_client,
        )

        self.assertEqual([cue.text for cue in translated], [f"\u0110\u00e3 d\u1ecbch Source {index}" for index in range(1, 5)])
        self.assertEqual([cue.index for cue in translated], [1, 2, 3, 4])

    def test_translate_cues_splits_a_batch_when_ai_returns_too_few_lines(self) -> None:
        cues = [
            SubtitleCue(index=1, start_ms=0, end_ms=1000, text="\u7b2c\u4e00\u53e5"),
            SubtitleCue(index=2, start_ms=1000, end_ms=2000, text="\u7b2c\u4e8c\u53e5"),
        ]
        requested_texts: list[list[str]] = []

        def fake_client(messages, _options):
            payload = json.loads(messages[1]["content"].rsplit("\n\n", 1)[-1])
            texts = [item["text"] for item in payload]
            requested_texts.append(texts)
            if len(texts) == 2:
                return json.dumps({"translations": ["Ch\u1ec9 c\u00f3 m\u1ed9t d\u00f2ng."]}, ensure_ascii=False)
            translated_text = "C\u00e2u th\u1ee9 nh\u1ea5t." if texts[0] == "\u7b2c\u4e00\u53e5" else "C\u00e2u th\u1ee9 hai."
            return json.dumps({"translations": [translated_text]}, ensure_ascii=False)

        translated = translate_cues(
            cues,
            AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
                batch_size=2,
            ),
            client=fake_client,
        )

        self.assertEqual(
            requested_texts,
            [["\u7b2c\u4e00\u53e5", "\u7b2c\u4e8c\u53e5"], ["\u7b2c\u4e00\u53e5"], ["\u7b2c\u4e8c\u53e5"]],
        )
        self.assertEqual([cue.text for cue in translated], ["C\u00e2u th\u1ee9 nh\u1ea5t.", "C\u00e2u th\u1ee9 hai."])
        self.assertEqual([cue.start_ms for cue in translated], [0, 1000])

    def test_translate_cues_resumes_only_missing_batches_from_checkpoint(self) -> None:
        cues = [
            SubtitleCue(index=index, start_ms=index * 1000, end_ms=(index + 1) * 1000, text=f"Source {index}")
            for index in range(1, 5)
        ]
        calls: list[str] = []
        fail_second_batch = True

        def fake_client(messages, _options):
            nonlocal fail_second_batch
            payload = json.loads(messages[1]["content"].rsplit("\n\n", 1)[-1])
            calls.append(payload[0]["text"])
            if payload[0]["text"] == "Source 3" and fail_second_batch:
                raise RuntimeError("temporary API failure")
            return json.dumps(
                {"translations": [f"\u0110\u00e3 d\u1ecbch {item['text']}" for item in payload]},
                ensure_ascii=False,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "translation.json"
            options = AITranslationOptions(
                source_language="en",
                target_language="vi",
                api_key="secret-key-must-not-be-cached",
                model="test-model",
                batch_size=2,
                max_workers=1,
            )
            with self.assertRaisesRegex(RuntimeError, "temporary API failure"):
                translate_cues(cues, options, client=fake_client, checkpoint_path=checkpoint_path)

            fail_second_batch = False
            translated = translate_cues(cues, options, client=fake_client, checkpoint_path=checkpoint_path)

            self.assertEqual(calls, ["Source 1", "Source 3", "Source 3"])
            self.assertEqual([cue.text for cue in translated], [f"\u0110\u00e3 d\u1ecbch Source {index}" for index in range(1, 5)])
            self.assertNotIn("secret-key-must-not-be-cached", checkpoint_path.read_text(encoding="utf-8"))

    def test_parallel_translation_checkpoints_successes_that_finish_after_a_failure(self) -> None:
        cues = [
            SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Source 1"),
            SubtitleCue(index=2, start_ms=1000, end_ms=2000, text="Source 2"),
        ]
        first_attempt_started = threading.Barrier(2)
        fail_second_cue = True
        calls: list[str] = []

        def fake_client(messages, _options):
            nonlocal fail_second_cue
            payload = json.loads(messages[1]["content"].rsplit("\n\n", 1)[-1])
            source_text = payload[0]["text"]
            calls.append(source_text)
            if len(calls) <= 2:
                first_attempt_started.wait(timeout=2)
            if source_text == "Source 1" and fail_second_cue:
                time.sleep(0.05)
            if source_text == "Source 2" and fail_second_cue:
                raise RuntimeError("temporary API failure")
            return json.dumps({"translations": [f"\u0110\u00e3 d\u1ecbch {source_text}"]}, ensure_ascii=False)

        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "translation.json"
            options = AITranslationOptions(
                source_language="en",
                target_language="vi",
                api_key="test-key",
                model="test-model",
                batch_size=1,
                max_workers=2,
            )
            with self.assertRaisesRegex(RuntimeError, "temporary API failure"):
                translate_cues(cues, options, client=fake_client, checkpoint_path=checkpoint_path)

            fail_second_cue = False
            translated = translate_cues(cues, options, client=fake_client, checkpoint_path=checkpoint_path)

        self.assertEqual(calls.count("Source 1"), 1)
        self.assertEqual(calls.count("Source 2"), 2)
        self.assertEqual([cue.text for cue in translated], ["\u0110\u00e3 d\u1ecbch Source 1", "\u0110\u00e3 d\u1ecbch Source 2"])

    def test_parallel_translation_stops_scheduling_new_batches_after_a_failure(self) -> None:
        cues = [
            SubtitleCue(index=index, start_ms=index * 1000, end_ms=(index + 1) * 1000, text=f"Source {index}")
            for index in range(1, 21)
        ]
        calls: list[str] = []
        calls_lock = threading.Lock()

        def fake_client(messages, _options):
            payload = json.loads(messages[1]["content"].rsplit("\n\n", 1)[-1])
            source_text = payload[0]["text"]
            with calls_lock:
                calls.append(source_text)
            if source_text == "Source 1":
                raise RuntimeError("API is unavailable")
            time.sleep(0.05)
            return json.dumps({"translations": [f"\u0110\u00e3 d\u1ecbch {source_text}"]}, ensure_ascii=False)

        with self.assertRaisesRegex(RuntimeError, "API is unavailable"):
            translate_cues(
                cues,
                AITranslationOptions(
                    source_language="en",
                    target_language="vi",
                    api_key="test-key",
                    model="test-model",
                    batch_size=1,
                    max_workers=2,
                ),
                client=fake_client,
            )

        self.assertLessEqual(len(calls), 2)

    def test_parallel_translation_never_exceeds_six_requests(self) -> None:
        cues = [
            SubtitleCue(index=index, start_ms=index * 1000, end_ms=(index + 1) * 1000, text=f"Source {index}")
            for index in range(1, 9)
        ]
        active = 0
        maximum_active = 0
        active_lock = threading.Lock()

        def fake_client(messages, _options):
            nonlocal active, maximum_active
            payload = json.loads(messages[1]["content"].rsplit("\n\n", 1)[-1])
            source_text = payload[0]["text"]
            with active_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.05)
            with active_lock:
                active -= 1
            return json.dumps({"translations": [f"\u0110\u00e3 d\u1ecbch {source_text}"]}, ensure_ascii=False)

        translate_cues(
            cues,
            AITranslationOptions(
                source_language="en",
                target_language="vi",
                api_key="test-key",
                model="test-model",
                batch_size=1,
                max_workers=16,
            ),
            client=fake_client,
        )

        self.assertLessEqual(maximum_active, 6)

    def test_mixed_batch_checkpoints_correct_cue_when_failed_cue_retry_raises(self) -> None:
        cues = [
            SubtitleCue(index=1, start_ms=0, end_ms=1000, text="\u7b2c\u4e00\u53e5"),
            SubtitleCue(index=2, start_ms=1000, end_ms=2000, text="\u7b2c\u4e8c\u53e5"),
        ]
        fail_retry = True
        requested_texts: list[list[str]] = []

        def fake_client(messages, _options):
            nonlocal fail_retry
            payload = json.loads(messages[1]["content"].rsplit("\n\n", 1)[-1])
            texts = [item["text"] for item in payload]
            requested_texts.append(texts)
            if len(texts) == 2:
                return json.dumps(
                    {"translations": ["C\u00e2u \u0111\u1ea7u \u0111\u00e3 d\u1ecbch.", "\u8fd8\u662f\u4e2d\u6587"]},
                    ensure_ascii=False,
                )
            if fail_retry:
                raise RuntimeError("temporary API failure")
            return json.dumps({"translations": ["C\u00e2u th\u1ee9 hai \u0111\u00e3 d\u1ecbch."]}, ensure_ascii=False)

        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "translation.json"
            options = AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
                batch_size=2,
            )
            with self.assertRaisesRegex(RuntimeError, "temporary API failure"):
                translate_cues(cues, options, client=fake_client, checkpoint_path=checkpoint_path)

            fail_retry = False
            translated = translate_cues(cues, options, client=fake_client, checkpoint_path=checkpoint_path)

        self.assertEqual(
            requested_texts,
            [["\u7b2c\u4e00\u53e5", "\u7b2c\u4e8c\u53e5"], ["\u7b2c\u4e8c\u53e5"], ["\u7b2c\u4e8c\u53e5"]],
        )
        self.assertEqual(
            [cue.text for cue in translated],
            ["C\u00e2u \u0111\u1ea7u \u0111\u00e3 d\u1ecbch.", "C\u00e2u th\u1ee9 hai \u0111\u00e3 d\u1ecbch."],
        )

    def test_translate_cues_warns_once_when_checkpoint_cannot_be_saved(self) -> None:
        cues = [
            SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Source 1"),
            SubtitleCue(index=2, start_ms=1000, end_ms=2000, text="Source 2"),
        ]
        warnings: list[str] = []

        def fake_client(messages, _options):
            payload = json.loads(messages[1]["content"].rsplit("\n\n", 1)[-1])
            return json.dumps(
                {"translations": [f"\u0110\u00e3 d\u1ecbch {item['text']}" for item in payload]},
                ensure_ascii=False,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.translator.write_json_atomic", side_effect=PermissionError("file is locked")):
                translated = translate_cues(
                    cues,
                    AITranslationOptions(
                        source_language="en",
                        target_language="vi",
                        api_key="test-key",
                        model="test-model",
                        batch_size=1,
                    ),
                    client=fake_client,
                    checkpoint_path=Path(temp_dir) / "translation.json",
                    warning=warnings.append,
                )

        self.assertEqual([cue.text for cue in translated], ["\u0110\u00e3 d\u1ecbch Source 1", "\u0110\u00e3 d\u1ecbch Source 2"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("checkpoint", warnings[0].lower())
        self.assertIn("file is locked", warnings[0])

    def test_translate_cues_preserves_timing_and_order(self) -> None:
        cues = [
            SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hello there."),
            SubtitleCue(index=2, start_ms=1000, end_ms=2000, text="Welcome back."),
        ]

        def fake_client(messages, _options):
            self.assertIn("Hello there.", messages[1]["content"])
            return json.dumps(
                {"translations": ["Xin ch\u00e0o.", "Ch\u00e0o m\u1eebng quay l\u1ea1i."]},
                ensure_ascii=False,
            )

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

        self.assertEqual([cue.text for cue in translated], ["Xin ch\u00e0o.", "Ch\u00e0o m\u1eebng quay l\u1ea1i."])
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

    def test_translate_cues_retries_a_short_english_response_for_vietnamese(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=520, text="\u7b49\u4e00\u4e0b")
        responses = iter([["Wait a second"], ["Ch\u1edd m\u1ed9t ch\u00fat."]])
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "Ch\u1edd m\u1ed9t ch\u00fat.")
        self.assertEqual(call_count, 2)

    def test_translate_cues_retries_short_english_content_words_for_vietnamese(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="\u6311\u6218\u5b8c\u6210")
        responses = iter([["Challenge completed"], ["Th\u1eed th\u00e1ch \u0111\u00e3 ho\u00e0n th\u00e0nh."]])
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "Th\u1eed th\u00e1ch \u0111\u00e3 ho\u00e0n th\u00e0nh.")
        self.assertEqual(call_count, 2)

    def test_translate_cues_adds_vietnamese_context_to_an_unchanged_title_case_name(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Minecraft Live")
        responses = iter([["Minecraft Live"], ["S\u1ef1 ki\u1ec7n Minecraft Live"]])
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="auto",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "S\u1ef1 ki\u1ec7n Minecraft Live")
        self.assertEqual(call_count, 2)

    def test_translate_cues_retries_a_single_common_english_word(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="\u7b49")
        responses = iter([["Wait"], ["Ch\u1edd."]])
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "Ch\u1edd.")
        self.assertEqual(call_count, 2)

    def test_translate_cues_retries_an_unknown_single_ascii_word(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="\u7206\u70b8")
        responses = iter([["Explosion"], ["V\u1ee5 n\u1ed5."]])
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "V\u1ee5 n\u1ed5.")
        self.assertEqual(call_count, 2)

    def test_translate_cues_accepts_an_unmarked_vietnamese_phrase(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="\u513f\u5b50")
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": ["Con trai"]})

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "Con trai")
        self.assertEqual(call_count, 1)

    def test_translate_cues_accepts_another_unmarked_vietnamese_phrase(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="\u7535\u5f71\u5f88\u597d")

        def fake_client(_messages, _options):
            return json.dumps({"translations": ["Phim hay"]})

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "Phim hay")

    def test_translate_cues_retries_an_unchanged_english_command(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Run")
        responses = iter([["Run"], ["Ch\u1ea1y."]])

        def fake_client(_messages, _options):
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="en",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "Ch\u1ea1y.")

    def test_translate_cues_retries_short_mixed_english_and_vietnamese(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="\u8fd9\u662f\u4e00\u4e2a\u6d4b\u8bd5")
        responses = iter([["This is m\u1ed9t test"], ["\u0110\u00e2y l\u00e0 m\u1ed9t b\u00e0i ki\u1ec3m tra."]])
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "\u0110\u00e2y l\u00e0 m\u1ed9t b\u00e0i ki\u1ec3m tra.")
        self.assertEqual(call_count, 2)

    def test_translate_cues_retries_english_when_target_uses_another_script(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hello")
        responses = iter([["Still English"], ["\u3053\u3093\u306b\u3061\u306f"]])
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="en",
                target_language="ja",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "\u3053\u3093\u306b\u3061\u306f")
        self.assertEqual(call_count, 2)

    def test_translate_cues_retries_english_for_a_french_target(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hello")
        responses = iter([["This is still English"], ["Ceci est toujours en français"]])

        def fake_client(_messages, _options):
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="en",
                target_language="fr",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "Ceci est toujours en français")

    def test_translate_cues_accepts_a_short_french_sentence(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="We are done")
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": ["On a fini."]}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="en",
                target_language="fr",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "On a fini.")
        self.assertEqual(call_count, 1)

    def test_translate_cues_retries_chinese_for_an_english_target(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hello")
        responses = iter([["这仍然是中文"], ["This is English"]])

        def fake_client(_messages, _options):
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="zh",
                target_language="en",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "This is English")

    def test_translate_cues_retries_a_chinese_sentence_for_a_japanese_target(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="这是一个中文句子")
        responses = iter([["这仍然是一个中文句子"], ["これは日本語の字幕です"]])

        def fake_client(_messages, _options):
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="zh",
                target_language="ja",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "これは日本語の字幕です")

    def test_translate_cues_preserves_an_unchanged_single_name(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Minecraft")
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": ["Minecraft"]})

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="auto",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "Minecraft")
        self.assertEqual(call_count, 1)

    def test_translate_cues_accepts_vietnamese_with_circumflex_marks(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="\u5feb\u5feb\u5feb")

        def fake_client(_messages, _options):
            return json.dumps(
                {"translations": ["Nhanh l\u00ean nhanh l\u00ean nhanh l\u00ean"]},
                ensure_ascii=False,
            )

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "Nhanh l\u00ean nhanh l\u00ean nhanh l\u00ean")

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
                self.assertIn("Ph\u1ea3n h\u1ed3i tr\u01b0\u1edbc v\u1eabn \u0111\u01b0\u1ee3c vi\u1ebft b\u1eb1ng Chinese", messages[1]["content"])
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

    def test_translate_cues_retries_a_single_character_chinese_cue(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=520, text="\u597d")
        responses = iter([["\u597d"], ["\u0110\u01b0\u1ee3c."]])
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="auto",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "\u0110\u01b0\u1ee3c.")
        self.assertEqual(call_count, 2)

    def test_translate_cues_retries_vietnamese_text_containing_one_han_character(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="\u5c31\u6210\u4e86\u4e00\u6761\u76f4\u7ebf")
        responses = iter(
            [
                ["\u5c31 tr\u1edf th\u00e0nh m\u1ed9t \u0111\u01b0\u1eddng th\u1eb3ng"],
                ["N\u00f3 tr\u1edf th\u00e0nh m\u1ed9t \u0111\u01b0\u1eddng th\u1eb3ng"],
            ]
        )
        call_count = 0

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps({"translations": next(responses)}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "N\u00f3 tr\u1edf th\u00e0nh m\u1ed9t \u0111\u01b0\u1eddng th\u1eb3ng")
        self.assertEqual(call_count, 2)

    def test_vietnamese_translation_prompt_uses_vietnamese_instructions_and_example(self) -> None:
        cue = SubtitleCue(
            index=1,
            start_ms=0,
            end_ms=3760,
            text="\u6211\u7684\u4e16\u754c\uff0c\u4f46\u53ea\u80fd\u4f7f\u7528\u4e00\u683c\u7269\u54c1",
        )
        call_count = 0

        def fake_client(messages, _options):
            nonlocal call_count
            call_count += 1
            prompt = "\n".join(message["content"] for message in messages)
            if "Nhi\u1ec7m v\u1ee5 duy nh\u1ea5t" in prompt and "Ch\u1edd m\u1ed9t ch\u00fat" in prompt:
                return json.dumps({"translations": ["Th\u1ebf gi\u1edbi c\u1ee7a t\u00f4i"]}, ensure_ascii=False)
            return json.dumps({"translations": ["\u8fd9\u4ecd\u7136\u662f\u4e2d\u6587\u5b57\u5e55"]}, ensure_ascii=False)

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="auto",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "Th\u1ebf gi\u1edbi c\u1ee7a t\u00f4i")
        self.assertEqual(call_count, 1)

    def test_translate_cues_uses_plain_text_fallback_for_a_stubborn_chinese_cue(self) -> None:
        cue = SubtitleCue(
            index=1,
            start_ms=0,
            end_ms=1720,
            text="\u4e5f\u4f1a\u4ea7\u751f\u540c\u6837\u7684\u7206\u70b8",
        )
        call_count = 0

        def fake_client(messages, _options):
            nonlocal call_count
            call_count += 1
            prompt = "\n".join(message["content"] for message in messages)
            if "\u4e2d\u8d8a\u7ffb\u8bd1" in prompt:
                return "C\u0169ng s\u1ebd t\u1ea1o ra v\u1ee5 n\u1ed5 t\u01b0\u01a1ng t\u1ef1."
            return json.dumps(
                {"translations": ["\u4e5f\u4f1a\u4ea7\u751f\u540c\u6837\u7684\u7206\u70b8"]},
                ensure_ascii=False,
            )

        translated = translate_cues(
            [cue],
            AITranslationOptions(
                source_language="auto",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
        )

        self.assertEqual(translated[0].text, "C\u0169ng s\u1ebd t\u1ea1o ra v\u1ee5 n\u1ed5 t\u01b0\u01a1ng t\u1ef1.")
        self.assertEqual(call_count, 3)

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

    def test_translate_cues_splits_chinese_batches_down_to_single_cues(self) -> None:
        cues = [
            SubtitleCue(
                index=index,
                start_ms=index * 1000,
                end_ms=(index + 1) * 1000,
                text=f"\u8fd9\u662f\u7b2c {index} \u884c\u5b57\u5e55",
            )
            for index in range(1, 6)
        ]
        batch_sizes: list[int] = []

        def fake_client(messages, _options):
            batch_size = messages[1]["content"].count('"index"')
            batch_sizes.append(batch_size)
            language = "\u4e2d\u6587\u5b57\u5e55" if batch_size > 1 else "b\u1ea3n d\u1ecbch ti\u1ebfng Vi\u1ec7t"
            return json.dumps(
                {"translations": [f"{language} {index}" for index in range(1, batch_size + 1)]},
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

        self.assertEqual(batch_sizes, [5, 2, 1, 1, 3, 1, 2, 1, 1])
        self.assertTrue(all("b\u1ea3n d\u1ecbch ti\u1ebfng Vi\u1ec7t" in cue.text for cue in translated))

    def test_translate_cues_retries_only_the_wrong_cue_from_a_mixed_batch(self) -> None:
        cues = [
            SubtitleCue(index=1, start_ms=0, end_ms=1000, text="\u7b2c\u4e00\u53e5"),
            SubtitleCue(index=2, start_ms=1000, end_ms=2000, text="\u7b2c\u4e8c\u53e5"),
        ]
        requested_texts: list[list[str]] = []

        def fake_client(messages, _options):
            payload = json.loads(messages[1]["content"].rsplit("\n\n", 1)[-1])
            texts = [item["text"] for item in payload]
            requested_texts.append(texts)
            if len(texts) == 2:
                return json.dumps(
                    {"translations": ["C\u00e2u \u0111\u1ea7u \u0111\u00e3 d\u1ecbch", "\u8fd8\u662f\u4e2d\u6587"]},
                    ensure_ascii=False,
                )
            return json.dumps({"translations": ["C\u00e2u th\u1ee9 hai \u0111\u00e3 d\u1ecbch"]}, ensure_ascii=False)

        translated = translate_cues(
            cues,
            AITranslationOptions(
                source_language="zh",
                target_language="vi",
                api_key="test-key",
                model="test-model",
                batch_size=2,
            ),
            client=fake_client,
        )

        self.assertEqual(requested_texts, [["\u7b2c\u4e00\u53e5", "\u7b2c\u4e8c\u53e5"], ["\u7b2c\u4e8c\u53e5"]])
        self.assertEqual([cue.text for cue in translated], ["C\u00e2u \u0111\u1ea7u \u0111\u00e3 d\u1ecbch", "C\u00e2u th\u1ee9 hai \u0111\u00e3 d\u1ecbch"])

    def test_translate_cues_rejects_output_when_language_does_not_improve(self) -> None:
        cues = [
            SubtitleCue(index=index, start_ms=index * 1000, end_ms=(index + 1) * 1000, text=f"这是第 {index} 行")
            for index in range(1, 21)
        ]
        call_count = 0
        warnings: list[str] = []

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

        with self.assertRaisesRegex(RuntimeError, "English"):
            translate_cues(
                cues,
                AITranslationOptions(
                    source_language="auto",
                    target_language="vi",
                    api_key="test-key",
                    model="test-model",
                ),
                client=fake_client,
                warning=warnings.append,
            )

        self.assertEqual(call_count, 2)
        self.assertTrue(
            any("English" in warning for warning in warnings),
            f"Expected a warning about English output, got: {warnings}",
        )

    def test_translate_cues_rejects_output_when_chinese_persists(self) -> None:
        cues = [
            SubtitleCue(
                index=1,
                start_ms=0,
                end_ms=3760,
                text="\u6211\u7684\u4e16\u754c\uff0c\u4f46\u53ea\u80fd\u4f7f\u7528\u4e00\u683c\u7269\u54c1",
            )
        ]
        call_count = 0
        warnings: list[str] = []

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return json.dumps(
                {"translations": ["\u8fd9\u4ecd\u7136\u662f\u4e00\u53e5\u4e2d\u6587\u5b57\u5e55"]},
                ensure_ascii=False,
            )

        with self.assertRaisesRegex(RuntimeError, "Chinese"):
            translate_cues(
                cues,
                AITranslationOptions(
                    source_language="auto",
                    target_language="vi",
                    api_key="test-key",
                    model="test-model",
                ),
                client=fake_client,
                warning=warnings.append,
            )

        self.assertEqual(call_count, 3)
        self.assertTrue(
            any("Chinese" in warning for warning in warnings),
            f"Expected a warning about Chinese output, got: {warnings}",
        )

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
            return json.dumps({"translations": ["Xin ch\u00e0o."]}, ensure_ascii=False)

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

        self.assertEqual(translated[0].text, "Xin ch\u00e0o.")

    def test_translate_script_text_preserves_blank_lines(self) -> None:
        def fake_client(_messages, _options):
            return json.dumps(
                {"translations": ["Xin ch\u00e0o.", "Th\u1ebf gi\u1edbi."]},
                ensure_ascii=False,
            )

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

        self.assertEqual(translated, "Xin ch\u00e0o.\n\nTh\u1ebf gi\u1edbi.")

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


    def test_extract_translations_salvages_missing_colon(self) -> None:
        raw = '{"translations" ["Câu một", "Câu hai"]}'
        result = _extract_translations(raw)
        self.assertEqual(result, ["Câu một", "Câu hai"])

    def test_extract_translations_salvages_trailing_comma(self) -> None:
        raw = '{"translations": ["Một", "Hai",]}'
        result = _extract_translations(raw)
        self.assertEqual(result, ["Một", "Hai"])

    def test_extract_translations_salvages_text_around_json(self) -> None:
        raw = 'Sure! Here you go:\n\n{"translations": ["Xin chào.", "Tạm biệt."]}\n\nHope that helps!'
        result = _extract_translations(raw)
        self.assertEqual(result, ["Xin chào.", "Tạm biệt."])

    def test_extract_translations_salvages_code_block_with_broken_json(self) -> None:
        raw = '```json\n{"translations": ["OK", "Fine"]\n```'
        result = _extract_translations(raw)
        self.assertEqual(result, ["OK", "Fine"])

    def test_extract_translations_handles_valid_json_normally(self) -> None:
        raw = '{"translations": ["Bình thường.", "Không lỗi."]}'
        result = _extract_translations(raw)
        self.assertEqual(result, ["Bình thường.", "Không lỗi."])

    def test_salvage_json_recovers_from_missing_colon(self) -> None:
        cleaned = '{"translations" ["Một", "Hai"]}'
        result = _salvage_json_translations(cleaned)
        self.assertEqual(result, ["Một", "Hai"])

    def test_salvage_json_rejects_unrelated_quoted_strings(self) -> None:
        cleaned = 'some garbage {"câu một" "câu hai"} more garbage'
        result = _salvage_json_translations(cleaned)
        self.assertIsNone(result)

    def test_salvage_json_returns_none_when_nothing_can_be_recovered(self) -> None:
        self.assertIsNone(_salvage_json_translations("not json"))

    def test_extract_translations_preserves_the_original_json_error(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            _extract_translations("not json")

    def test_translation_options_repr_hides_api_key(self) -> None:
        options = AITranslationOptions(
            source_language="en",
            target_language="vi",
            api_key="secret-key",
        )

        self.assertNotIn("secret-key", repr(options))

    def test_translation_rejects_http_api_url_when_key_is_present(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "HTTPS"):
            validate_translation_options(
                AITranslationOptions(
                    source_language="en",
                    target_language="vi",
                    api_key="secret-key",
                    base_url="http://api.example.com/v1",
                )
            )

    def test_translation_allows_http_for_a_local_api(self) -> None:
        validate_translation_options(
            AITranslationOptions(
                source_language="en",
                target_language="vi",
                base_url="http://127.0.0.1:11434/v1",
            )
        )

    def test_invalid_language_output_is_not_written_to_checkpoint(self) -> None:
        cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hello")

        def fake_client(_messages, _options):
            return json.dumps({"translations": ["Still English"]})

        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = Path(temp_dir) / "translation.json"
            with self.assertRaisesRegex(RuntimeError, "English"):
                translate_cues(
                    [cue],
                    AITranslationOptions(
                        source_language="en",
                        target_language="vi",
                        api_key="test-key",
                    ),
                    client=fake_client,
                    checkpoint_path=checkpoint_path,
                )

            self.assertFalse(checkpoint_path.exists())

    def test_translate_cues_retries_malformed_json_and_falls_back(self) -> None:
        cues = [
            SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hello."),
            SubtitleCue(index=2, start_ms=1000, end_ms=2000, text="World."),
        ]
        call_count = 0
        warnings: list[str] = []

        def fake_client(_messages, _options):
            nonlocal call_count
            call_count += 1
            return '{"translations" ["Xin chào.", "Thế giới."]}'

        translated = translate_cues(
            cues,
            AITranslationOptions(
                source_language="en",
                target_language="vi",
                api_key="test-key",
                model="test-model",
            ),
            client=fake_client,
            warning=warnings.append,
        )

        # First attempt: salvageJSON repair succeeds (missing colon)
        self.assertEqual(len(translated), 2)
        self.assertEqual(translated[0].text, "Xin chào.")
        self.assertEqual(translated[1].text, "Thế giới.")
        self.assertEqual(call_count, 1)

    def test_translate_cues_retries_unrecoverable_json(self) -> None:
        cues = [
            SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hi."),
        ]
        call_count = 0
        warnings: list[str] = []
        requests: list[list[dict[str, str]]] = []

        def fake_client(messages, _options):
            nonlocal call_count
            call_count += 1
            requests.append(messages)
            return "completely broken response with no json at all"

        with self.assertRaisesRegex(RuntimeError, "JSON"):
            translate_cues(
                cues,
                AITranslationOptions(
                    source_language="en",
                    target_language="vi",
                    api_key="test-key",
                    model="test-model",
                ),
                client=fake_client,
                warning=warnings.append,
            )

        self.assertEqual(call_count, 2)
        retry_prompt = "\n".join(message["content"] for message in requests[1])
        self.assertIn("JSON", retry_prompt)


if __name__ == "__main__":
    unittest.main()
