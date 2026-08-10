from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.text_splitter import normalize_text, split_text  # noqa: E402


class TextSplitterTests(unittest.TestCase):
    def test_normalize_text_preserves_paragraph_breaks(self) -> None:
        text = "  Cau mot.  \n\n  Cau hai   keo dai. "

        self.assertEqual(normalize_text(text), "Cau mot.\nCau hai keo dai.")

    def test_split_text_uses_sentence_boundaries(self) -> None:
        chunks = split_text("Cau mot. Cau hai? Cau ba!", max_chars=80)

        self.assertEqual(chunks, ["Cau mot.", "Cau hai?", "Cau ba!"])

    def test_split_text_chunks_long_sentences(self) -> None:
        text = " ".join([f"word{i}" for i in range(30)])
        chunks = split_text(text, max_chars=60)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 60 for chunk in chunks))

    def test_split_text_discards_symbol_only_chunks(self) -> None:
        chunks = split_text("Xin chao. ... Tam biet.\n\n♪", max_chars=80)

        self.assertEqual(chunks, ["Xin chao.", "Tam biet."])

    def test_split_text_keeps_common_abbreviations_with_their_sentence(self) -> None:
        chunks = split_text(
            "Dr. Smith measured 3.14 units. Visit https://example.com/a.b now.",
            max_chars=120,
        )

        self.assertEqual(
            chunks,
            [
                "Dr. Smith measured 3.14 units.",
                "Visit https://example.com/a.b now.",
            ],
        )

    def test_split_text_can_end_a_sentence_after_us_abbreviation(self) -> None:
        chunks = split_text("I live in the U.S. It is large.", max_chars=120)

        self.assertEqual(chunks, ["I live in the U.S.", "It is large."])

    def test_split_text_keeps_us_with_a_following_proper_name(self) -> None:
        chunks = split_text("The U.S. Army arrived.", max_chars=120)

        self.assertEqual(chunks, ["The U.S. Army arrived."])


if __name__ == "__main__":
    unittest.main()
