from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from ..studio.models import (
    OUTPUT_FORMATS,
    VOICE_SOURCES,
    StudioGenerationSpec,
    StudioVoiceSelection,
)


BATCH_ITEM_STATUSES = ("pending", "running", "done", "failed")
BATCH_RUN_STATUSES = (
    "queued",
    "running",
    "paused",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "interrupted",
)


@dataclass(frozen=True)
class BatchItemSpec:
    item_id: str
    text: str
    language: str = ""
    speed: float | None = None
    duration: float | None = None
    voice_source: str = ""
    profile_id: str = ""
    instruction: str = ""
    formats: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.item_id.strip():
            raise ValueError("Mỗi mục Batch phải có ID.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", self.item_id):
            raise ValueError(
                f"ID Batch không hợp lệ: {self.item_id}. Chỉ dùng chữ, số, dấu chấm, gạch ngang và gạch dưới."
            )
        if not self.text.strip():
            raise ValueError(f"Mục {self.item_id} chưa có nội dung.")
        if self.speed is not None and not 0.5 <= self.speed <= 1.5:
            raise ValueError(f"Tốc độ của {self.item_id} phải từ 0.5 đến 1.5.")
        if self.duration is not None and self.duration <= 0:
            raise ValueError(f"Thời lượng của {self.item_id} phải lớn hơn 0.")
        if self.voice_source and self.voice_source not in VOICE_SOURCES:
            raise ValueError(f"Nguồn giọng của {self.item_id} không hợp lệ: {self.voice_source}")
        if self.voice_source == "profile" and not self.profile_id.strip():
            raise ValueError(f"Mục {self.item_id} chưa chọn profile giọng.")
        if self.voice_source == "design" and not self.instruction.strip():
            raise ValueError(f"Mục {self.item_id} chưa có mô tả giọng.")
        if self.formats and any(value not in OUTPUT_FORMATS for value in self.formats):
            raise ValueError(f"Định dạng của {self.item_id} chỉ hỗ trợ WAV và MP3.")

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["formats"] = list(self.formats)
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> BatchItemSpec:
        return cls(
            item_id=str(payload.get("item_id") or payload.get("id") or ""),
            text=str(payload.get("text") or ""),
            language=str(payload.get("language") or payload.get("language_id") or ""),
            speed=float(payload["speed"]) if payload.get("speed") not in (None, "") else None,
            duration=(
                float(payload["duration"])
                if payload.get("duration") not in (None, "")
                else None
            ),
            voice_source=str(payload.get("voice_source") or ""),
            profile_id=str(payload.get("profile_id") or ""),
            instruction=str(payload.get("instruction") or ""),
            formats=tuple(str(item).lower() for item in payload.get("formats") or ()),
        )


@dataclass(frozen=True)
class BatchSpec:
    project_id: str
    title: str
    output_dir: str
    engine_id: str = "omnivoice"
    model_id: str = "k2-fsa/OmniVoice"
    device: str = "auto"
    language: str = "vi"
    speed: float = 1.0
    duration: float | None = None
    formats: tuple[str, ...] = ("wav", "mp3")
    voice: StudioVoiceSelection = field(default_factory=StudioVoiceSelection)
    engine_options: dict[str, Any] = field(default_factory=dict)
    combine: bool = False
    gap_ms: int = 250

    def validate(self) -> None:
        if not self.project_id.strip():
            raise ValueError("Hãy chọn hoặc tạo một dự án trước khi chạy Batch.")
        if not self.title.strip():
            raise ValueError("Batch phải có tên.")
        if not self.output_dir.strip():
            raise ValueError("Hãy chọn thư mục xuất Batch.")
        if not self.engine_id.strip():
            raise ValueError("Batch chưa chỉ định engine.")
        if self.voice.source not in VOICE_SOURCES:
            raise ValueError(f"Nguồn giọng không hợp lệ: {self.voice.source}")
        if self.voice.source == "profile" and not self.voice.profile_id.strip():
            raise ValueError("Hãy chọn một profile giọng đã lưu.")
        if self.voice.source == "reference" and not self.voice.reference_audio.strip():
            raise ValueError("Hãy chọn audio tham chiếu.")
        if self.voice.source == "design" and not self.voice.instruction.strip():
            raise ValueError("Hãy mô tả giọng cần thiết kế.")
        if not 0.5 <= self.speed <= 1.5:
            raise ValueError("Tốc độ mặc định phải từ 0.5 đến 1.5.")
        if not self.formats or any(value not in OUTPUT_FORMATS for value in self.formats):
            raise ValueError("Batch chỉ hỗ trợ WAV và MP3.")
        if not 0 <= self.gap_ms <= 5000:
            raise ValueError("Khoảng nghỉ khi ghép phải từ 0 đến 5000 ms.")

    def item_generation_spec(self, item: BatchItemSpec, batch_dir: str) -> StudioGenerationSpec:
        source = item.voice_source or self.voice.source
        profile_id = item.profile_id or self.voice.profile_id
        instruction = item.instruction or self.voice.instruction
        return StudioGenerationSpec(
            project_id=self.project_id,
            title=item.item_id,
            text=item.text,
            engine_id=self.engine_id,
            language=item.language or self.language,
            output_dir=batch_dir,
            output_name=item.item_id,
            model_id=self.model_id,
            device=self.device,
            speed=item.speed if item.speed is not None else self.speed,
            duration=item.duration if item.duration is not None else self.duration,
            formats=item.formats or self.formats,
            voice=StudioVoiceSelection(
                source=source,
                profile_id=profile_id,
                reference_audio=self.voice.reference_audio,
                reference_text=self.voice.reference_text,
                instruction=instruction,
            ),
            engine_options=dict(self.engine_options),
        )

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["formats"] = list(self.formats)
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> BatchSpec:
        voice = payload.get("voice") if isinstance(payload.get("voice"), dict) else {}
        return cls(
            project_id=str(payload.get("project_id") or ""),
            title=str(payload.get("title") or "Batch"),
            output_dir=str(payload.get("output_dir") or ""),
            engine_id=str(payload.get("engine_id") or "omnivoice"),
            model_id=str(payload.get("model_id") or "k2-fsa/OmniVoice"),
            device=str(payload.get("device") or "auto"),
            language=str(payload.get("language") or "vi"),
            speed=float(payload.get("speed") or 1.0),
            duration=(
                float(payload["duration"])
                if payload.get("duration") not in (None, "")
                else None
            ),
            formats=tuple(str(item).lower() for item in payload.get("formats") or ("wav", "mp3")),
            voice=StudioVoiceSelection(
                source=str(voice.get("source") or "auto"),
                profile_id=str(voice.get("profile_id") or ""),
                reference_audio=str(voice.get("reference_audio") or ""),
                reference_text=str(voice.get("reference_text") or ""),
                instruction=str(voice.get("instruction") or ""),
            ),
            engine_options=dict(payload.get("engine_options") or {}),
            combine=bool(payload.get("combine", False)),
            gap_ms=int(payload.get("gap_ms", 250)),
        )


@dataclass
class BatchItemState:
    spec: BatchItemSpec
    status: str = "pending"
    attempts: int = 0
    error: str = ""
    project_dir: str = ""
    wav_path: str = ""
    mp3_path: str = ""
    manifest_path: str = ""
    warnings: tuple[str, ...] = ()


@dataclass
class BatchRun:
    batch_id: str
    spec: BatchSpec
    root_dir: str
    manifest_path: str
    local_path: str
    items: list[BatchItemState]
    status: str = "queued"
    task_id: str = ""
    combined_wav_path: str = ""
    combined_mp3_path: str = ""
    warnings: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @property
    def completed_count(self) -> int:
        return sum(item.status == "done" for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.status == "failed" for item in self.items)
