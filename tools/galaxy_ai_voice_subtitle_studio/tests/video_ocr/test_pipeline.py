from __future__ import annotations

import unittest

from app.video_ocr.models import OcrObservation
from app.video_ocr.pipeline import (
    FrameProbe,
    group_probes,
    representative_probes,
    rescue_probe,
    signature_distance,
)
from app.video_ocr.tracking import drop_static_cues, merge_observations, vote_observations
from app.video_ocr.worker import _engine


class OcrPipelineTests(unittest.TestCase):
    def test_builds_a_vietnamese_latin_recognizer_without_slowing_the_detector(self) -> None:
        class ModelTypes:
            TINY = "tiny"
            SMALL = "small"
            MOBILE = "mobile"

        captured: dict[str, object] = {}

        def rapid_ocr(*, params):
            captured.update(params)
            return object()

        _engine("fast", "vi", ModelTypes, rapid_ocr)

        self.assertEqual(captured["Det.model_type"], "tiny")
        self.assertEqual(captured["Rec.lang_type"], "latin")
        self.assertEqual(captured["Rec.model_type"], "mobile")
        self.assertEqual(captured["Rec.ocr_version"], "PP-OCRv5")

    def test_groups_stable_probes_and_selects_bounded_representatives(self) -> None:
        probes = (
            FrameProbe(0, 0, bytes([0b00000000]), 0.1),
            FrameProbe(15, 500, bytes([0b00000001]), 0.4),
            FrameProbe(30, 1_000, bytes([0b00000001]), 0.3),
            FrameProbe(45, 1_500, bytes([0b11111111]), 0.8),
        )

        runs = group_probes(probes, change_threshold=2, maximum_run_ms=3_000)

        self.assertEqual([[probe.frame_index for probe in run.probes] for run in runs], [[0, 15, 30], [45]])
        self.assertEqual([probe.frame_index for probe in representative_probes(runs[0], accurate=False)], [15])
        self.assertEqual([probe.frame_index for probe in representative_probes(runs[0], accurate=True)], [0, 15, 30])
        self.assertEqual(signature_distance(bytes([0b10100000]), bytes([0b00110000])), 2)

    def test_rescue_prefers_unread_probe_with_most_text_activity(self) -> None:
        run = group_probes(
            (
                FrameProbe(0, 0, b"\x00", 0.1),
                FrameProbe(15, 500, b"\x00", 0.8),
                FrameProbe(30, 1_000, b"\x00", 0.4),
            ),
            change_threshold=1,
            maximum_run_ms=3_000,
        )[0]

        selected = rescue_probe(run, excluded_frame_indices={0})

        self.assertIsNotNone(selected)
        self.assertEqual(selected.frame_index, 15)

    def test_temporal_vote_beats_a_single_high_confidence_outlier(self) -> None:
        winner = vote_observations(
            (
                OcrObservation(0, "Xin chào", 0.84),
                OcrObservation(500, "Xin chào", 0.86),
                OcrObservation(1_000, "Xln chà0", 0.98),
            ),
            similarity_threshold=0.82,
        )

        self.assertEqual(winner.text, "Xin chào")
        self.assertGreater(winner.confidence, 0.84)

    def test_filters_only_text_that_covers_almost_the_entire_video(self) -> None:
        cues = merge_observations(
            [
                OcrObservation(0, "GALAXY", 0.95),
                OcrObservation(5_000, "GALAXY", 0.95),
                OcrObservation(10_000, "GALAXY", 0.95),
            ],
            sample_interval_ms=5_000,
            duration_ms=12_000,
        )

        kept, static = drop_static_cues(cues, duration_ms=12_000)

        self.assertEqual(kept, ())
        self.assertEqual(static, cues)


if __name__ == "__main__":
    unittest.main()
