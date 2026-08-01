from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.srt import SubtitleCue  # noqa: E402
from app.translator import AITranslationOptions, translate_cues  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
