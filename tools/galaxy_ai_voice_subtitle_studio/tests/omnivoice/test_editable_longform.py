from __future__ import annotations

import unittest

from app.omnivoice.workspaces.editable import (
    EditableLongformDocument,
    EditableLongformItem,
)


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


if __name__ == "__main__":
    unittest.main()
