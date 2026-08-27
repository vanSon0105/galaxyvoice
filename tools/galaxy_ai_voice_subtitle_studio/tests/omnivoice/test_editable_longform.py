from __future__ import annotations

import unittest

from app.omnivoice.workspaces.editable import (
    EditableLongformDocument,
    EditableLongformItem,
)
from app.omnivoice.workspaces.expressive import PronunciationRule
from app.omnivoice.workspaces.longform import PAUSE_SPAN, SPEECH_SPAN


class EditableLongformDocumentTests(unittest.TestCase):
    def test_edit_split_merge_reorder_and_plan(self) -> None:
        document = EditableLongformDocument.from_story(
            "# Intro\nLan: Xin chao. Hom nay troi dep.\nMinh: Di thoi."
        )
        first = document.items[0]
        document.update(first.item_id, speed=0.9, pause_after_ms=600)
        left_id, right_id = document.split(first.item_id)
        document.move(right_id, 1)
        document.merge(left_id, right_id)

        plan = document.to_plan()

        self.assertEqual(len(document.items), 2)
        self.assertEqual(plan.voice_names, ("Lan", "Minh"))
        self.assertEqual(plan.spans[0].speed, 0.9)
        self.assertEqual(plan.spans[1].pause_ms, 600)

    def test_round_trip_keeps_item_identity_and_settings(self) -> None:
        document = EditableLongformDocument(
            items=[
                EditableLongformItem(
                    item_id="line-1",
                    chapter="One",
                    speaker="Narrator",
                    text="A line.",
                    speed=1.1,
                    volume=0.8,
                    pause_after_ms=250,
                )
            ],
            chapters=["One"],
        )

        restored = EditableLongformDocument.from_payload(document.to_payload())

        self.assertEqual(restored.items, document.items)
        self.assertEqual(restored.to_plan().spans[0].volume, 0.8)

    def test_document_converts_between_story_and_audiobook_scripts(self) -> None:
        document = EditableLongformDocument.from_story(
            "# Mở đầu\nLan: Xin chào. [pause 600ms]\nMinh: Đi thôi."
        )

        audiobook_script = document.to_script("audiobook")
        restored = EditableLongformDocument.from_audiobook(audiobook_script)

        self.assertIn("[voice:Lan] Xin chào. [pause 600ms]", audiobook_script)
        self.assertIn("[voice:Minh] Đi thôi.", audiobook_script)
        self.assertEqual([item.speaker for item in restored.items], ["Lan", "Minh"])
        self.assertEqual(restored.items[0].pause_after_ms, 600)

    def test_invalid_source_markup_is_rejected_before_document_creation(self) -> None:
        with self.assertRaisesRegex(ValueError, "Markup biểu cảm chưa hợp lệ"):
            EditableLongformDocument.from_story("Lan: [rate nhanh]Xin chào")

    def test_language_scoped_pronunciation_only_applies_to_matching_document(self) -> None:
        rule = PronunciationRule.create("Galaxy", "Ga-la-xi", language="vi")
        document = EditableLongformDocument(
            items=[EditableLongformItem("line-1", "One", "", "Galaxy")],
            chapters=["One"],
            language="en",
            pronunciation_rules=(rule,),
        )

        self.assertEqual(document.to_plan().spans[0].text, "Galaxy")

    def test_markup_inside_editor_line_keeps_local_rate_and_pause(self) -> None:
        document = EditableLongformDocument(
            items=[
                EditableLongformItem(
                    "line-1",
                    "One",
                    "Narrator",
                    "Xin [slow]chào[/slow] [pause 300ms] bạn",
                )
            ],
            chapters=["One"],
            language="vi",
        )

        plan = document.to_plan()

        self.assertEqual([span.kind for span in plan.spans], [SPEECH_SPAN, SPEECH_SPAN, PAUSE_SPAN, SPEECH_SPAN])
        self.assertEqual(plan.spans[1].speed, 0.85)
        self.assertEqual(plan.spans[2].pause_ms, 300)
        self.assertEqual([span.source_index for span in plan.spans if span.kind == SPEECH_SPAN], [1, 1, 1])

    def test_spoken_override_keeps_single_expression_but_rejects_ambiguous_pause(self) -> None:
        document = EditableLongformDocument(
            items=[
                EditableLongformItem(
                    "line-1",
                    "One",
                    "Narrator",
                    "[emotion vui]Galaxy[/emotion]",
                    spoken_text="Ga-la-xi",
                )
            ],
            chapters=["One"],
            language="vi",
        )

        plan = document.to_plan()
        self.assertEqual(plan.spans[0].text, "Ga-la-xi")
        self.assertEqual(plan.spans[0].display_text, "Galaxy")
        self.assertEqual(plan.spans[0].emotion, "vui")

        document.items[0] = EditableLongformItem(
            "line-1",
            "One",
            "Narrator",
            "Galaxy [pause 200ms] Studio",
            spoken_text="Ga-la-xi Studio",
        )
        self.assertIn(
            "spoken-override-conflict",
            {issue.code for issue in document.to_plan().issues},
        )

    def test_audiobook_has_default_narrator_and_chapter_management(self) -> None:
        document = EditableLongformDocument.from_audiobook("# One\nA line.")
        self.assertEqual(document.items[0].speaker, "Người kể")

        document.add_chapter("Two", after="One")
        document.rename_chapter("Two", "Second")
        document.move_chapter("Second", -1)

        self.assertEqual(document.chapters, ["Second", "One"])


if __name__ == "__main__":
    unittest.main()
