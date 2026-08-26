from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


VOICE_SOURCES = ("auto", "profile", "reference", "design")
OUTPUT_FORMATS = ("wav", "mp3")


@dataclass(frozen=True)
class StudioVoiceSelection:
    source: str = "auto"
    profile_id: str = ""
    reference_audio: str = ""
    reference_text: str = ""
    save_profile_name: str = ""
    instruction: str = ""
    consent_confirmed: bool = False
    consent_basis: str = ""
    consent_statement: str = ""


@dataclass(frozen=True)
class StudioGenerationSpec:
    project_id: str
    title: str
    text: str
    engine_id: str = "omnivoice"
    language: str = "vi"
    output_dir: str = ""
    output_name: str = "studio-take"
    model_id: str = "k2-fsa/OmniVoice"
    device: str = "auto"
    speed: float = 1.0
    duration: float | None = None
    formats: tuple[str, ...] = ("wav", "mp3")
    voice: StudioVoiceSelection = field(default_factory=StudioVoiceSelection)
    engine_options: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.text.strip():
            raise ValueError("Nhập nội dung cần tạo giọng.")
        if not self.project_id.strip():
            raise ValueError("Hãy chọn hoặc tạo một dự án trước khi tạo giọng.")
        if not self.engine_id.strip():
            raise ValueError("Yêu cầu Studio chưa chỉ định engine.")
        if self.voice.source not in VOICE_SOURCES:
            raise ValueError(f"Nguồn giọng không hợp lệ: {self.voice.source}")
        if self.voice.source == "profile" and not self.voice.profile_id.strip():
            raise ValueError("Hãy chọn một profile giọng đã lưu.")
        if self.voice.source == "reference" and not self.voice.reference_audio.strip():
            raise ValueError("Hãy chọn audio tham chiếu.")
        if self.voice.save_profile_name.strip() and not self.voice.consent_confirmed:
            raise ValueError("Phải xác nhận quyền sử dụng giọng nói trước khi lưu giọng nhái.")
        if self.voice.source == "design" and not self.voice.instruction.strip():
            raise ValueError("Hãy mô tả giọng cần thiết kế.")
        if not self.formats or any(item not in OUTPUT_FORMATS for item in self.formats):
            raise ValueError("Định dạng Studio chỉ hỗ trợ WAV và MP3.")
        if not 0.5 <= float(self.speed) <= 1.5:
            raise ValueError("Tốc độ phải nằm trong khoảng 0.5 đến 1.5.")

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["formats"] = list(self.formats)
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> StudioGenerationSpec:
        voice_payload = payload.get("voice") if isinstance(payload.get("voice"), dict) else {}
        return cls(
            project_id=str(payload.get("project_id") or ""),
            title=str(payload.get("title") or "Bản đọc"),
            text=str(payload.get("text") or ""),
            engine_id=str(payload.get("engine_id") or "omnivoice"),
            language=str(payload.get("language") or "vi"),
            output_dir=str(payload.get("output_dir") or ""),
            output_name=str(payload.get("output_name") or "studio-take"),
            model_id=str(payload.get("model_id") or "k2-fsa/OmniVoice"),
            device=str(payload.get("device") or "auto"),
            speed=float(payload.get("speed") or 1.0),
            duration=float(payload["duration"]) if payload.get("duration") else None,
            formats=tuple(str(item) for item in payload.get("formats") or ("wav", "mp3")),
            voice=StudioVoiceSelection(
                source=str(voice_payload.get("source") or "auto"),
                profile_id=str(voice_payload.get("profile_id") or ""),
                reference_audio=str(voice_payload.get("reference_audio") or ""),
                reference_text=str(voice_payload.get("reference_text") or ""),
                save_profile_name=str(voice_payload.get("save_profile_name") or ""),
                instruction=str(voice_payload.get("instruction") or ""),
                consent_confirmed=bool(voice_payload.get("consent_confirmed")),
                consent_basis=str(voice_payload.get("consent_basis") or ""),
                consent_statement=str(voice_payload.get("consent_statement") or ""),
            ),
            engine_options=dict(payload.get("engine_options") or {}),
        )


@dataclass(frozen=True)
class StudioArtifact:
    project_dir: Path
    wav_path: Path
    mp3_path: Path | None
    manifest_path: Path
    profile_id: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StudioTake:
    take_id: str
    project_id: str
    title: str
    engine_id: str
    spec: StudioGenerationSpec
    project_dir: str
    wav_path: str
    mp3_path: str
    manifest_path: str
    profile_id: str
    warnings: tuple[str, ...]
    generation_run_id: str
    rerun_of: str
    created_at: str

    @property
    def preview_path(self) -> str:
        return self.mp3_path or self.wav_path


@dataclass(frozen=True)
class StudioTakeView:
    """Immutable take plus mutable user/project annotations."""

    take: StudioTake
    starred: bool = False
    primary: bool = False
