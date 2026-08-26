from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any

from ..common.paths import slugify
from .models import BatchItemSpec


def parse_batch_source(source: str, *, long_form: bool = False) -> tuple[BatchItemSpec, ...]:
    if long_form:
        return _split_long_form(source)
    items: list[BatchItemSpec] = []
    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"JSONL dòng {line_number} không hợp lệ: {error.msg}") from error
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL dòng {line_number} phải là một object.")
            item = _item_from_json(payload, line_number)
        else:
            item = BatchItemSpec(item_id=f"voice-{line_number:03d}", text=line)
        item.validate()
        items.append(item)
    return _validate_items(items)


def validate_batch_items(items: list[BatchItemSpec]) -> tuple[BatchItemSpec, ...]:
    for item in items:
        item.validate()
    return _validate_items(items)


def _item_from_json(payload: dict[str, Any], line_number: int) -> BatchItemSpec:
    item_id = slugify(str(payload.get("id") or payload.get("item_id") or f"voice-{line_number:03d}"))
    formats_value = payload.get("formats") or ()
    if isinstance(formats_value, str):
        formats_value = [value.strip() for value in formats_value.split(",") if value.strip()]
    return BatchItemSpec(
        item_id=item_id,
        text=str(payload.get("text") or "").strip(),
        language=str(payload.get("language_id") or payload.get("language") or "").strip(),
        speed=_optional_float(payload.get("speed"), "speed", line_number),
        duration=_optional_float(payload.get("duration"), "duration", line_number),
        voice_source=str(payload.get("voice_source") or "").strip(),
        profile_id=str(payload.get("profile_id") or "").strip(),
        instruction=str(payload.get("instruction") or "").strip(),
        formats=tuple(str(value).strip().lower() for value in formats_value),
    )


def _split_long_form(source: str) -> tuple[BatchItemSpec, ...]:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [
        paragraph.strip().replace("\n", " ")
        for paragraph in re.split(r"\n(?:[ \t]*\n)+", normalized)
        if paragraph.strip()
    ]
    return _validate_items(
        [
            BatchItemSpec(item_id=f"part-{index:03d}", text=text)
            for index, text in enumerate(paragraphs, start=1)
        ]
    )


def _validate_items(items: list[BatchItemSpec]) -> tuple[BatchItemSpec, ...]:
    if not items:
        raise ValueError("Hãy nhập ít nhất một mục Batch.")
    duplicates = sorted(
        item_id
        for item_id, count in Counter(item.item_id for item in items).items()
        if count > 1
    )
    if duplicates:
        raise ValueError(f"ID Batch bị trùng: {', '.join(duplicates)}")
    return tuple(items)


def _optional_float(value: object, field_name: str, line_number: int) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"JSONL dòng {line_number}: {field_name} phải là số.") from error
