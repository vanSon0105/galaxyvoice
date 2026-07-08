from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.srt import SubtitleCue, format_timestamp, render_srt  # noqa: E402


class SrtTests(unittest.TestCase):
    def test_format_timestamp(self) -> None:
        self.assertEqual(format_timestamp(3_723_045), "01:02:03,045")

    def test_render_srt(self) -> None:
        srt = render_srt([SubtitleCue(index=1, start_ms=0, end_ms=1250, text="Hello")])

        self.assertEqual(
            srt,
            "1\n00:00:00,000 --> 00:00:01,250\nHello\n",
        )


if __name__ == "__main__":
    unittest.main()
