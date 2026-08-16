from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from typing import Any
from uuid import uuid4

from .longform import (
    PAUSE_SPAN,
    SPEECH_SPAN,
    LongformPlan,
    LongformSpan,
    parse_audiobook_script,
    parse_story_script,
)


@dataclass(frozen=True)
class EditableLongformItem:
    item_id: str
    chapter: str
    speaker: str
    text: str
    profile_id: str = ""
    speed: float = 1.0
    volume: float = 1.0
    pause_after_ms: int = 0
    preview_path: str = ""


class EditableLongformDocument:
    def __init__(
        self,
        *,
        items: list[EditableLongformItem],
        chapters: list[str],
    ) -> None:
        self.items = items
        self.chapters = list(dict.fromkeys(chapter for chapter in chapters if chapter))

    @classmethod
    def from_story(cls, source: str) -> EditableLongformDocument:
        return cls.from_plan(parse_story_script(source))

    @classmethod
    def from_audiobook(cls, source: str) -> EditableLongformDocument:
        return cls.from_plan(parse_audiobook_script(source))

    @classmethod
    def from_plan(cls, plan: LongformPlan) -> EditableLongformDocument:
        items: list[EditableLongformItem] = []
        for span in plan.spans:
            if span.kind == PAUSE_SPAN:
                if items:
                    items[-1] = replace(
                        items[-1],
                        pause_after_ms=items[-1].pause_after_ms + span.pause_ms,
                    )
                continue
            if span.kind != SPEECH_SPAN:
                continue
            items.append(
                EditableLongformItem(
                    item_id=f"line-{uuid4().hex[:10]}",
                    chapter=span.chapter,
                    speaker=span.voice_name,
                    text=span.text,
                    speed=span.speed,
                    volume=span.volume,
                )
            )
        return cls(items=items, chapters=list(plan.chapters))

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> EditableLongformDocument:
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("Project khong co danh sach doan hop le.")
        items = [
            EditableLongformItem(**item)
            for item in raw_items
            if isinstance(item, dict)
        ]
        chapters = payload.get("chapters")
        return cls(
            items=items,
            chapters=[str(value) for value in chapters] if isinstance(chapters, list) else [],
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "chapters": list(self.chapters),
            "items": [asdict(item) for item in self.items],
        }

    def to_script(self, kind: str) -> str:
        if kind not in {"stories", "audiobook"}:
            raise ValueError(f"Unsupported long-form workspace: {kind}")
        lines: list[str] = []
        current_chapter = ""
        for item in self.items:
            chapter = item.chapter.strip() or "Content"
            if chapter != current_chapter:
                if lines:
                    lines.append("")
                lines.append(f"# {chapter}")
                current_chapter = chapter

            text = item.text.strip()
            if not text:
                continue
            speaker = item.speaker.strip()
            if kind == "stories" and speaker:
                text = f"{speaker}: {text}"
            elif kind == "audiobook" and speaker:
                text = f"[voice:{speaker}] {text}"
            if item.pause_after_ms > 0:
                text = f"{text} [pause {item.pause_after_ms}ms]"
            lines.append(text)
        return "\n".join(lines).strip()

    def to_plan(self) -> LongformPlan:
        spans: list[LongformSpan] = []
        chapters: list[str] = list(self.chapters)
        for index, item in enumerate(self.items, start=1):
            chapter = item.chapter.strip() or "Content"
            if chapter not in chapters:
                chapters.append(chapter)
            if item.text.strip():
                spans.append(
                    LongformSpan(
                        kind=SPEECH_SPAN,
                        text=item.text.strip(),
                        voice_name=item.speaker.strip(),
                        profile_id=item.profile_id,
                        speed=max(0.5, min(1.5, float(item.speed))),
                        volume=max(0.0, min(2.0, float(item.volume))),
                        chapter=chapter,
                        source_index=index,
                    )
                )
            if item.pause_after_ms > 0:
                spans.append(
                    LongformSpan(
                        kind=PAUSE_SPAN,
                        pause_ms=max(0, min(10_000, int(item.pause_after_ms))),
                        chapter=chapter,
                    )
                )
        if not any(span.kind == SPEECH_SPAN for span in spans):
            raise ValueError("Project khong co noi dung de tao giong.")
        return LongformPlan(tuple(spans), tuple(chapters))

    def get(self, item_id: str) -> EditableLongformItem | None:
        return next((item for item in self.items if item.item_id == item_id), None)

    def update(self, item_id: str, **changes: object) -> EditableLongformItem:
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        updated = replace(item, **changes)
        self.items[self.items.index(item)] = updated
        if updated.chapter and updated.chapter not in self.chapters:
            self.chapters.append(updated.chapter)
        return updated

    def add(self, *, after_id: str = "", chapter: str = "") -> EditableLongformItem:
        item = EditableLongformItem(
            item_id=f"line-{uuid4().hex[:10]}",
            chapter=chapter or (self.items[-1].chapter if self.items else "Content"),
            speaker="",
            text="",
        )
        index = len(self.items)
        selected = self.get(after_id)
        if selected is not None:
            index = self.items.index(selected) + 1
        self.items.insert(index, item)
        return item

    def delete(self, item_id: str) -> None:
        self.items = [item for item in self.items if item.item_id != item_id]

    def move(self, item_id: str, delta: int) -> None:
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        old_index = self.items.index(item)
        new_index = max(0, min(len(self.items) - 1, old_index + int(delta)))
        if new_index == old_index:
            return
        self.items.pop(old_index)
        self.items.insert(new_index, item)

    def split(self, item_id: str, position: int | None = None) -> tuple[str, str]:
        item = self.get(item_id)
        if item is None:
            raise KeyError(item_id)
        split_at = _split_position(item.text, position)
        left_text = item.text[:split_at].strip()
        right_text = item.text[split_at:].strip()
        if not left_text or not right_text:
            raise ValueError("Khong tim thay vi tri tach hop le.")
        left = replace(item, text=left_text, pause_after_ms=0, preview_path="")
        right = replace(
            item,
            item_id=f"line-{uuid4().hex[:10]}",
            text=right_text,
            preview_path="",
        )
        index = self.items.index(item)
        self.items[index : index + 1] = [left, right]
        return left.item_id, right.item_id

    def merge(self, first_id: str, second_id: str) -> str:
        first = self.get(first_id)
        second = self.get(second_id)
        if first is None or second is None or first is second:
            raise ValueError("Can chon hai doan khac nhau de ghep.")
        first_index = self.items.index(first)
        second_index = self.items.index(second)
        merged = replace(
            first,
            text=f"{first.text.rstrip()} {second.text.lstrip()}".strip(),
            pause_after_ms=second.pause_after_ms,
            preview_path="",
        )
        insert_at = min(first_index, second_index)
        self.items = [item for item in self.items if item not in {first, second}]
        self.items.insert(insert_at, merged)
        return merged.item_id


def _split_position(text: str, requested: int | None) -> int:
    if requested is not None and 0 < int(requested) < len(text):
        return int(requested)
    middle = len(text) // 2
    boundaries = [match.end() for match in re.finditer(r"[.!?;:]\s+|\s+", text)]
    return min(boundaries, key=lambda value: abs(value - middle)) if boundaries else middle
