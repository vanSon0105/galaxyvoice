from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from app.omnivoice.workspaces.dubbing.model import (
    DubbingFitPolicy,
    DubbingSegment,
    DubbingSegmentMeasurement,
    build_dubbing_segments,
    build_dubbing_quality_report,
    merge_dubbing_segments,
    plan_dubbing_segments,
    split_dubbing_segment,
    validate_dubbing_segments,
)
from app.voice.srt import SubtitleCue
from app.omnivoice.workspaces.dubbing.project import (
    DubbingProject,
    DubbingProjectRepository,
    DubbingRevisionConflict,
)


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

    def test_validation_rejects_invalid_timing_and_duplicate_ids(self) -> None:
        issues = validate_dubbing_segments(
            (
                DubbingSegment("same", 1_000, 900, "x", "Một", "Lan"),
                DubbingSegment("same", 1_100, 1_500, "y", "Hai", "Lan"),
            )
        )

        codes = {issue.code for issue in issues}
        self.assertIn("invalid-timing", codes)
        self.assertIn("duplicate-id", codes)

    def test_quality_report_scores_gap_overrun_and_bounded_fit(self) -> None:
        segments = (
            DubbingSegment("a", 0, 1_000, "hello", "Xin chao", "Lan", profile_id="lan"),
            DubbingSegment("b", 1_040, 2_000, "bye", "Tam biet", "Minh"),
        )
        report = build_dubbing_quality_report(
            segments,
            measurements=(
                DubbingSegmentMeasurement(
                    segment_id="a",
                    raw_duration_ms=1_600,
                    tempo=1.25,
                    tempo_duration_ms=1_280,
                    fitted_duration_ms=1_000,
                    method="ffmpeg-atempo",
                    clipped_ms=280,
                ),
            ),
            policy=DubbingFitPolicy(min_gap_ms=80, max_tempo=1.25),
        )

        codes = {issue.code for issue in report.issues}
        self.assertIn("tight-gap", codes)
        self.assertIn("fit-limit", codes)
        self.assertIn("unmapped-speaker", codes)
        self.assertLess(report.score, 100)
        self.assertEqual(report.segment_count, 2)
        self.assertTrue(report.report_id)

    def test_quality_report_id_is_repeatable(self) -> None:
        segments = (DubbingSegment("a", 0, 1_000, "x", "Xin chao", "Lan", profile_id="lan"),)
        first = build_dubbing_quality_report(segments)
        second = build_dubbing_quality_report(segments)
        self.assertEqual(first.report_id, second.report_id)

    def test_project_repository_checkpoints_revision_and_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = DubbingProjectRepository(Path(temp_dir) / "dubbing.json")
            project = DubbingProject.create(
                name="Ban long tieng",
                source_srt="1\n00:00:00,000 --> 00:00:01,000\nHello\n",
                segments=(DubbingSegment("a", 0, 1_000, "Hello", "Xin chao", "Lan"),),
            )
            saved = repository.save(project, expected_revision=0)
            updated = repository.save(
                saved.evolved(stage="cast", translated_srt="translated"),
                expected_revision=saved.revision,
            )

            self.assertEqual(updated.revision, 2)
            self.assertEqual(repository.get(updated.project_id).stage, "cast")
            self.assertEqual(repository.list()[0].segment_count, 1)
            with self.assertRaises(DubbingRevisionConflict):
                repository.save(updated.evolved(name="stale"), expected_revision=1)


if __name__ == "__main__":
    unittest.main()
