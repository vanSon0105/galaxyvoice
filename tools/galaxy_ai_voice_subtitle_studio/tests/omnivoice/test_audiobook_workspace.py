from __future__ import annotations

import unittest

from app.omnivoice.workspaces.audiobook.planner import (
    AudiobookOverrides,
    build_audiobook_plan,
)


class AudiobookPlannerTests(unittest.TestCase):
    def test_plan_applies_lexicon_cast_and_chapter_overrides(self) -> None:
        plan = build_audiobook_plan(
            "# Chương 1\n[voice:Lan] OpenAI bắt đầu.\n# Chương 2\n[voice:Minh] Kết thúc.",
            cast={"Lan": "lan-vi", "Minh": "minh-vi"},
            lexicon={"OpenAI": "Ô-pần Ây-ai"},
            overrides={"Chương 2": AudiobookOverrides(speed=0.9, pause_after_ms=800)},
        )

        self.assertEqual(len(plan.chapters), 2)
        self.assertIn("Ô-pần Ây-ai", plan.chapters[0].spans[0].text)
        self.assertEqual(plan.chapters[0].spans[0].profile_id, "lan-vi")
        self.assertEqual(plan.chapters[1].speed, 0.9)
        self.assertEqual(plan.chapters[1].pause_after_ms, 800)
        self.assertFalse(plan.errors)

    def test_plan_warns_for_unassigned_cast_and_oversized_lines(self) -> None:
        plan = build_audiobook_plan(
            "# Chương 1\n[voice:Lan] " + ("nội dung " * 100),
            cast={},
            lexicon={},
            max_span_chars=120,
        )

        codes = {issue.code for issue in plan.warnings}
        self.assertIn("unassigned-voice", codes)
        self.assertIn("long-span", codes)
        self.assertGreater(plan.stats.word_count, 50)
        self.assertGreater(plan.stats.estimated_seconds, 0)


if __name__ == "__main__":
    unittest.main()
