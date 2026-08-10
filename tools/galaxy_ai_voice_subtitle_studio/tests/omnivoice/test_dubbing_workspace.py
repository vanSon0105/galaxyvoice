from __future__ import annotations

import unittest

from app.omnivoice.workspaces.dubbing.model import (
    DubbingSegment,
    build_dubbing_segments,
    merge_dubbing_segments,
    plan_dubbing_segments,
    split_dubbing_segment,
    validate_dubbing_segments,
)
from app.voice.srt import SubtitleCue


class DubbingWorkspaceModelTests(unittest.TestCase):
    def test_build_detects_speaker_prefixes_and_keeps_translations(self) -> None:
        segments = build_dubbing_segments(
            [
                SubtitleCue(1, 0, 1_000, "[speaker:Lan] 你好"),
                SubtitleCue(2, 1_200, 2_200, "Minh: 再见"),
            ],
            [
                SubtitleCue(1, 0, 1_000, "Xin chào"),
                SubtitleCue(2, 1_200, 2_200, "Tạm biệt"),
            ],
        )

        self.assertEqual([segment.speaker_id for segment in segments], ["Lan", "Minh"])
        self.assertEqual([segment.source_text for segment in segments], ["你好", "再见"])
        self.assertEqual([segment.text for segment in segments], ["Xin chào", "Tạm biệt"])

    def test_split_merge_and_plan_preserve_timeline_and_voice(self) -> None:
        original = DubbingSegment(
            segment_id="seg-1",
            start_ms=1_000,
            end_ms=3_000,
            source_text="Một câu. Hai câu.",
            text="Một câu. Hai câu.",
            speaker_id="Lan",
            profile_id="lan-vi",
        )

        left, right = split_dubbing_segment(original)
        merged = merge_dubbing_segments(left, right)
        plan = plan_dubbing_segments((left, right))

        self.assertEqual(left.end_ms, right.start_ms)
        self.assertEqual(merged.start_ms, 1_000)
        self.assertEqual(merged.end_ms, 3_000)
        speech = [span for span in plan.spans if span.text]
        self.assertEqual([span.voice_name for span in speech], ["Lan", "Lan"])
        self.assertEqual([span.duration for span in speech], [1.0, 1.0])

    def test_validation_reports_overlap_empty_text_and_reading_pressure(self) -> None:
        issues = validate_dubbing_segments(
            (
                DubbingSegment("a", 0, 500, "", "", "Lan"),
                DubbingSegment("b", 400, 600, "x", "Một câu dịch quá dài cho thời gian này", "Minh"),
            )
        )

        codes = {issue.code for issue in issues}
        self.assertIn("empty", codes)
        self.assertIn("overlap", codes)
        self.assertIn("reading-pressure", codes)


if __name__ == "__main__":
    unittest.main()
