from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path

from app.omnivoice.batch import (
    generate_omnivoice_batch,
    parse_batch_items,
    split_long_form,
)
from app.omnivoice.models import AUTO_MODE, OmniVoiceGenerationOptions


class _FakeClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def request(self, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
        self.payloads.append(payload)
        output = Path(str(payload["output_path"]))
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(24_000)
            target.writeframes(b"\x01\x00" * 2_400)
        return {"output_path": str(output)}


class OmniVoiceBatchParsingTests(unittest.TestCase):
    def test_plain_lines_and_jsonl_are_supported(self) -> None:
        items = parse_batch_items(
            'Xin chào\n{"id":"intro","text":"Hello","language_id":"en","speed":1.2}'
        )

        self.assertEqual([item.item_id for item in items], ["voice-001", "intro"])
        self.assertEqual(items[1].language, "en")
        self.assertEqual(items[1].speed, 1.2)

    def test_invalid_jsonl_reports_the_line(self) -> None:
        with self.assertRaisesRegex(ValueError, "dòng 2"):
            parse_batch_items('Hello\n{"text":')

    def test_duplicate_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "bị trùng"):
            parse_batch_items('{"id":"same","text":"A"}\n{"id":"same","text":"B"}')

    def test_long_form_splits_blank_line_paragraphs(self) -> None:
        items = split_long_form("Đoạn một.\n\nĐoạn hai\nvẫn tiếp tục.")

        self.assertEqual(len(items), 2)
        self.assertEqual(items[1].text, "Đoạn hai vẫn tiếp tục.")

    def test_long_form_splits_whitespace_only_blank_lines(self) -> None:
        items = split_long_form("Đoạn một.\n   \nĐoạn hai.")

        self.assertEqual([item.text for item in items], ["Đoạn một.", "Đoạn hai."])


class OmniVoiceBatchServiceTests(unittest.TestCase):
    def test_batch_reuses_worker_and_writes_completed_manifest(self) -> None:
        client = _FakeClient()
        items = parse_batch_items("Câu một\nCâu hai")
        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate_omnivoice_batch(
                OmniVoiceGenerationOptions(
                    mode=AUTO_MODE,
                    text="unused",
                    output_dir=Path(temp_dir),
                    project_name="batch-test",
                    export_mp3=False,
                ),
                items,
                client,
            )

            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["completed"])
            self.assertEqual(len(result.item_results), 2)
            self.assertEqual(len(client.payloads), 2)

    def test_long_form_combines_generated_wavs(self) -> None:
        client = _FakeClient()
        items = split_long_form("Đoạn một.\n\nĐoạn hai.")
        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate_omnivoice_batch(
                OmniVoiceGenerationOptions(
                    mode=AUTO_MODE,
                    text="unused",
                    output_dir=Path(temp_dir),
                    project_name="book-test",
                    export_mp3=False,
                ),
                items,
                client,
                combine=True,
                gap_ms=100,
            )

            self.assertIsNotNone(result.combined_wav_path)
            assert result.combined_wav_path is not None
            with wave.open(str(result.combined_wav_path), "rb") as combined:
                self.assertEqual(combined.getnframes(), 7_200)


if __name__ == "__main__":
    unittest.main()
