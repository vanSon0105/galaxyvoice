from __future__ import annotations

import unittest

from app.video_editor.model import (
    VIDEO_ASSET,
    EditorAsset,
    fit_cues_to_duration,
    format_timecode,
    normalize_cues,
    parse_timecode,
)
from app.voice.srt import SubtitleCue


class EditorModelTests(unittest.TestCase):
    def test_editor_asset_exposes_source_name_and_validates_kind(self) -> None:
        asset = EditorAsset("asset-1", VIDEO_ASSET, r"D:\Media\clip.mp4")

        self.assertEqual(asset.name, "clip.mp4")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            EditorAsset("asset-2", "image", "cover.png")

    def test_normalize_cues_sorts_clamps_and_reindexes(self) -> None:
        cues = [
            SubtitleCue(8, 2_000, 3_000, "Second"),
            SubtitleCue(3, -100, 500, " First "),
            SubtitleCue(9, 4_500, 6_000, "Past end"),
            SubtitleCue(10, 1_000, 1_500, "  "),
        ]

        result = normalize_cues(cues, duration_ms=5_000)

        self.assertEqual(
            result,
            [
                SubtitleCue(1, 0, 500, "First"),
                SubtitleCue(2, 2_000, 3_000, "Second"),
                SubtitleCue(3, 4_500, 5_000, "Past end"),
            ],
        )

    def test_fit_cues_stretches_track_to_video_duration(self) -> None:
        cues = [
            SubtitleCue(1, 1_000, 2_000, "One"),
            SubtitleCue(2, 3_000, 5_000, "Two"),
        ]

        result = fit_cues_to_duration(cues, 8_000)

        self.assertEqual(result[0].start_ms, 0)
        self.assertEqual(result[-1].end_ms, 8_000)
        self.assertEqual([cue.index for cue in result], [1, 2])

    def test_timecode_parsing_accepts_editor_formats(self) -> None:
        self.assertEqual(parse_timecode("75.25"), 75_250)
        self.assertEqual(parse_timecode("01:15.250"), 75_250)
        self.assertEqual(parse_timecode("01:02:03,004"), 3_723_004)
        self.assertEqual(format_timecode(75_250), "01:15.250")


if __name__ == "__main__":
    unittest.main()
