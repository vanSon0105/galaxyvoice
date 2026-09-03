from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from typing import Any

from ..common.errors import TaskCancelledError
from ..voice.text_splitter import normalize_text
from ..voice.translator import AITranslationOptions, ChatClient, complete_chat, resolve_translation_options


@dataclass(frozen=True)
class CueCondensationSpec:
    track_id: str
    cue_id: str
    text: str
    language: str
    cue_duration_ms: int
    audio_duration_ms: int

    def validate(self) -> None:
        if not self.track_id.strip() or not self.cue_id.strip():
            raise ValueError("Đề xuất rút gọn phải giữ track và cue gốc.")
        if not normalize_text(self.text):
            raise ValueError("Câu phụ đề chưa có nội dung để rút gọn.")
        if self.cue_duration_ms <= 0 or self.audio_duration_ms <= 0:
            raise ValueError("Thiếu thời lượng cue hoặc audio để tính mức rút gọn.")
        if self.audio_duration_ms <= self.cue_duration_ms:
            raise ValueError("Audio đã vừa cue nên không cần rút gọn phụ đề.")

    @property
    def target_characters(self) -> int:
        source_length = len(normalize_text(self.text))
        fitted = int(source_length * self.cue_duration_ms / self.audio_duration_ms * 0.95)
        return max(1, min(source_length - 1, fitted))


@dataclass(frozen=True)
class CueCondensationResult:
    track_id: str
    cue_id: str
    original_text: str
    proposed_text: str
    target_characters: int
    provider: str
    model: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class CueCondensationService:
    def propose(
        self,
        spec: CueCondensationSpec,
        options: AITranslationOptions,
        *,
        client: ChatClient | None = None,
        stop_event: threading.Event | None = None,
    ) -> CueCondensationResult:
        spec.validate()
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelledError()
        resolved = resolve_translation_options(options)
        messages = _condensation_messages(spec)
        raw = (client or complete_chat)(messages, resolved)
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelledError()
        proposed = _proposal_text(raw)
        original = normalize_text(spec.text)
        if len(normalize_text(proposed)) >= len(original):
            raise RuntimeError("AI chưa tạo được đề xuất ngắn hơn câu gốc.")
        return CueCondensationResult(
            track_id=spec.track_id,
            cue_id=spec.cue_id,
            original_text=spec.text,
            proposed_text=proposed,
            target_characters=spec.target_characters,
            provider=resolved.provider,
            model=resolved.model,
        )


def _condensation_messages(spec: CueCondensationSpec) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Bạn là biên tập viên phụ đề. Hãy rút gọn nhưng giữ nguyên ý nghĩa, "
                "tên riêng, con số và ngôn ngữ gốc; không thêm thông tin, không giải thích. "
                'Chỉ trả JSON đúng dạng {"text":"..."}.'
            ),
        },
        {
            "role": "user",
            "content": (
                f"Ngôn ngữ: {spec.language or 'auto'}\n"
                f"Mục tiêu tối đa khoảng {spec.target_characters} ký tự.\n"
                f"Câu gốc: {json.dumps(spec.text, ensure_ascii=False)}"
            ),
        },
    ]


def _proposal_text(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise RuntimeError("AI trả về đề xuất không đúng định dạng JSON.") from error
    proposed = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
    if not proposed:
        raise RuntimeError("AI trả về đề xuất rỗng.")
    return proposed
