from __future__ import annotations

import json
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
from .expressive import (
    PAUSE_DIRECTIVE,
    ExpressiveIssue,
    PronunciationRule,
    compile_expressive_text,
    expression_instruction,
    pronunciation_rules_from_payload,
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
    spoken_text: str = ""
    emotion: str = ""
    emphasis: bool = False
    spell: bool = False


class EditableLongformDocument:
    def __init__(
        self,
        *,
        items: list[EditableLongformItem],
        chapters: list[str],
        language: str = "auto",
        pronunciation_rules: tuple[PronunciationRule, ...] = (),
    ) -> None:
        self.items = items
        self.chapters = list(dict.fromkeys(chapter for chapter in chapters if chapter))
        self.language = language.strip().lower() or "auto"
        self.pronunciation_rules = pronunciation_rules

    @classmethod
    def from_story(cls, source: str, *, language: str = "auto") -> EditableLongformDocument:
        return cls.from_plan(
            _validated_source_plan(parse_story_script(source, language=language)),
            language=language,
        )

    @classmethod
    def from_audiobook(cls, source: str, *, language: str = "auto") -> EditableLongformDocument:
        return cls.from_plan(
            _validated_source_plan(parse_audiobook_script(source, language=language)),
            language=language,
            default_speaker="Người kể",
        )

    @classmethod
    def from_plan(
        cls,
        plan: LongformPlan,
        *,
        language: str = "auto",
        default_speaker: str = "",
    ) -> EditableLongformDocument:
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
                    speaker=span.voice_name or default_speaker,
                    text=span.display_text or span.text,
                    speed=span.speed,
                    volume=span.volume,
                    spoken_text=span.text if span.display_text and span.display_text != span.text else "",
                    emotion=span.emotion,
                    emphasis=span.emphasis,
                    spell=span.spell,
                )
            )
        return cls(items=items, chapters=list(plan.chapters), language=language)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        language: str = "",
    ) -> EditableLongformDocument:
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
            language=language or str(payload.get("language") or "auto"),
            pronunciation_rules=pronunciation_rules_from_payload(payload.get("pronunciation_rules")),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "chapters": list(self.chapters),
            "language": self.language,
            "items": [asdict(item) for item in self.items],
            "pronunciation_rules": [rule.to_dict() for rule in self.pronunciation_rules],
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

            text = _item_markup(item)
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
        issues: list[ExpressiveIssue] = []
        for index, item in enumerate(self.items, start=1):
            chapter = item.chapter.strip() or "Content"
            if chapter not in chapters:
                chapters.append(chapter)
            if item.text.strip():
                display_text = item.text.strip()
                compiled = compile_expressive_text(
                    display_text,
                    language=self.language,
                    pronunciation_rules=self.pronunciation_rules,
                    base_rate=float(item.speed),
                    base_spell=item.spell,
                )
                issues.extend(compiled.issues)
                speech_directives = [
                    directive
                    for directive in compiled.directives
                    if directive.kind != PAUSE_DIRECTIVE
                ]
                spoken_override = item.spoken_text.strip()
                if spoken_override and len(speech_directives) != 1:
                    issues.append(
                        ExpressiveIssue(
                            "spoken-override-conflict",
                            "Cach doc rieng chi dung duoc khi dong khong bi tach boi pause hoac nhieu the bieu cam.",
                            "error",
                            0,
                        )
                    )
                for directive in compiled.directives:
                    if directive.kind == PAUSE_DIRECTIVE:
                        spans.append(
                            LongformSpan(
                                kind=PAUSE_SPAN,
                                pause_ms=directive.pause_ms,
                                chapter=chapter,
                                source_index=index,
                            )
                        )
                        continue
                    spoken_text = (
                        spoken_override
                        if spoken_override and len(speech_directives) == 1
                        else directive.spoken_text
                    )
                    if item.spell and spoken_override:
                        spoken_text = " ".join(
                            character for character in spoken_text if not character.isspace()
                        )
                    emotion = item.emotion.strip() or directive.emotion
                    emphasis = bool(item.emphasis or directive.emphasis)
                    instruction = " ".join(
                        part
                        for part in (
                            directive.instruction.strip(),
                            expression_instruction(
                                emphasis=item.emphasis,
                                emotion=item.emotion,
                            ),
                        )
                        if part
                    )
                    spans.append(
                        LongformSpan(
                            kind=SPEECH_SPAN,
                            text=spoken_text,
                            display_text=directive.display_text,
                            voice_name=item.speaker.strip(),
                            profile_id=item.profile_id,
                            speed=directive.rate,
                            volume=max(0.0, min(2.0, float(item.volume))),
                            chapter=chapter,
                            source_index=index,
                            instruction=instruction,
                            emotion=emotion,
                            emphasis=emphasis,
                            spell=bool(item.spell or directive.spell),
                        )
                    )
            if item.pause_after_ms > 0:
                spans.append(
                    LongformSpan(
                        kind=PAUSE_SPAN,
                        pause_ms=max(0, min(10_000, int(item.pause_after_ms))),
                        chapter=chapter,
                        source_index=index,
                    )
                )
        if not any(span.kind == SPEECH_SPAN for span in spans):
            raise ValueError("Project khong co noi dung de tao giong.")
        return LongformPlan(tuple(spans), tuple(chapters), tuple(issues))

    def get(self, item_id: str) -> EditableLongformItem | None:
        return next((item for item in self.items if item.item_id == item_id), None)

    def assign_default_speaker(self, speaker: str) -> None:
        default = speaker.strip()
        if not default:
            return
        self.items = [
            item if item.speaker.strip() else replace(item, speaker=default)
            for item in self.items
        ]

    def add_chapter(self, name: str, *, after: str = "") -> None:
        chapter = name.strip()
        if not chapter:
            raise ValueError("Ten chuong khong duoc de trong.")
        if chapter in self.chapters:
            raise ValueError("Chuong da ton tai.")
        index = len(self.chapters)
        if after in self.chapters:
            index = self.chapters.index(after) + 1
        self.chapters.insert(index, chapter)

    def rename_chapter(self, chapter: str, name: str) -> None:
        renamed = name.strip()
        if chapter not in self.chapters:
            raise KeyError(chapter)
        if not renamed:
            raise ValueError("Ten chuong khong duoc de trong.")
        if renamed != chapter and renamed in self.chapters:
            raise ValueError("Chuong da ton tai.")
        self.chapters[self.chapters.index(chapter)] = renamed
        self.items = [
            replace(item, chapter=renamed) if item.chapter == chapter else item
            for item in self.items
        ]

    def move_chapter(self, chapter: str, delta: int) -> None:
        if chapter not in self.chapters:
            raise KeyError(chapter)
        old_index = self.chapters.index(chapter)
        new_index = max(0, min(len(self.chapters) - 1, old_index + int(delta)))
        if new_index == old_index:
            return
        self.chapters.pop(old_index)
        self.chapters.insert(new_index, chapter)

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
            speaker=self.items[-1].speaker if self.items else "",
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
        left = replace(
            item,
            text=left_text,
            pause_after_ms=0,
            preview_path="",
            spoken_text="",
        )
        right = replace(
            item,
            item_id=f"line-{uuid4().hex[:10]}",
            text=right_text,
            preview_path="",
            spoken_text="",
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
            spoken_text="",
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


def _item_markup(item: EditableLongformItem) -> str:
    text = item.text.strip()
    if not text:
        return ""
    if item.spoken_text.strip() and item.spoken_text.strip() != text:
        text = f"[pronounce {json.dumps(item.spoken_text.strip(), ensure_ascii=False)}]{text}[/pronounce]"
    if item.spell:
        text = f"[spell]{text}[/spell]"
    if item.emphasis:
        text = f"[emphasis]{text}[/emphasis]"
    if item.emotion.strip():
        text = f"[emotion {json.dumps(item.emotion.strip(), ensure_ascii=False)}]{text}[/emotion]"
    if abs(float(item.speed) - 1.0) > 0.001:
        text = f"[rate {float(item.speed):.3f}]{text}[/rate]"
    return text


def _validated_source_plan(plan: LongformPlan) -> LongformPlan:
    errors = [issue.message for issue in plan.issues if issue.severity == "error"]
    if errors:
        raise ValueError("Markup biểu cảm chưa hợp lệ: " + "; ".join(errors))
    return plan
