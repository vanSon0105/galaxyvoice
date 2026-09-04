from __future__ import annotations

import unittest

from app.video_ocr.models import OcrBox, OcrObservation
from app.video_ocr.tracking import drop_static_cues, merge_observations, text_similarity


class OcrTrackingTests(unittest.TestCase):
    def test_merges_repeated_caption_frames_and_uses_best_text(self) -> None:
        cues = merge_observations(
            [
                OcrObservation(500, "Xin chao", 0.72, (OcrBox(10, 20, 100, 24),)),
                OcrObservation(1_000, "Xin chào", 0.96, (OcrBox(8, 19, 105, 26),)),
                OcrObservation(1_500, "Xin chào", 0.94, (OcrBox(9, 20, 104, 25),)),
                OcrObservation(2_000, "", 0.0),
            ],
            sample_interval_ms=500,
            duration_ms=5_000,
        )

        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].text, "Xin chào")
        self.assertEqual((cues[0].start_ms, cues[0].end_ms), (250, 2_000))
        self.assertEqual(cues[0].boxes, (OcrBox(8, 19, 105, 26),))

    def test_splits_changed_text_and_large_time_gaps(self) -> None:
        cues = merge_observations(
            [
                OcrObservation(0, "Một", 0.9),
                OcrObservation(500, "Hai", 0.9),
                OcrObservation(3_000, "Hai", 0.9),
            ],
            sample_interval_ms=500,
            duration_ms=4_000,
        )

        self.assertEqual([cue.text for cue in cues], ["Một", "Hai", "Hai"])
        self.assertGreater(text_similarity("Xin  chào", "xin chào"), 0.99)

    def test_static_detection_returns_candidates_without_mutating_input(self) -> None:
        cues = merge_observations(
            [OcrObservation(timestamp, "Ten kenh", 0.9) for timestamp in range(0, 10_000, 500)],
            sample_interval_ms=500,
            duration_ms=10_000,
        )

        kept, candidates = drop_static_cues(cues, duration_ms=10_000)

        self.assertEqual(kept, ())
        self.assertEqual(candidates, cues)


if __name__ == "__main__":
    unittest.main()
