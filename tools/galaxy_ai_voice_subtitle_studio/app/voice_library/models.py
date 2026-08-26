from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


VOICE_SOURCES = ("system", "imported", "cloned", "designed")


@dataclass(frozen=True)
class ConsentRecord:
    confirmed: bool = False
    basis: str = ""
    statement: str = ""
    recorded_at: str = ""
    provenance: str = ""

    @classmethod
    def from_payload(cls, payload: object) -> ConsentRecord:
        data = payload if isinstance(payload, dict) else {}
        return cls(
            confirmed=bool(data.get("confirmed")),
            basis=str(data.get("basis") or ""),
            statement=str(data.get("statement") or ""),
            recorded_at=str(data.get("recorded_at") or ""),
            provenance=str(data.get("provenance") or ""),
        )


@dataclass(frozen=True)
class VoiceSelection:
    source: str
    profile_id: str = ""
    reference_audio: str = ""
    reference_text: str = ""
    instruction: str = ""
    system_engine: str = ""
    system_voice: str = ""


@dataclass(frozen=True)
class VoiceProfileRecord:
    voice_id: str
    revision: int
    name: str
    source: str
    language: str
    engine_id: str
    selection: VoiceSelection
    tags: tuple[str, ...] = ()
    notes: str = ""
    favorite: bool = False
    consent: ConsentRecord = field(default_factory=ConsentRecord)
    reference_asset: str = ""
    prompt_asset: str = ""
    stable_sample: bool = False
    created_at: str = ""
    updated_at: str = ""
    capabilities: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        payload["capabilities"] = list(self.capabilities)
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> VoiceProfileRecord:
        selection = payload.get("selection") if isinstance(payload.get("selection"), dict) else {}
        source = str(payload.get("source") or "imported")
        if source not in VOICE_SOURCES:
            source = "imported"
        return cls(
            voice_id=str(payload.get("voice_id") or ""),
            revision=max(1, int(payload.get("revision") or 1)),
            name=str(payload.get("name") or "Untitled voice"),
            source=source,
            language=str(payload.get("language") or "auto"),
            engine_id=str(payload.get("engine_id") or "omnivoice"),
            selection=VoiceSelection(
                source=str(selection.get("source") or "reference"),
                profile_id=str(selection.get("profile_id") or ""),
                reference_audio=str(selection.get("reference_audio") or ""),
                reference_text=str(selection.get("reference_text") or ""),
                instruction=str(selection.get("instruction") or ""),
                system_engine=str(selection.get("system_engine") or ""),
                system_voice=str(selection.get("system_voice") or ""),
            ),
            tags=tuple(str(item) for item in payload.get("tags") or () if str(item).strip()),
            notes=str(payload.get("notes") or ""),
            favorite=bool(payload.get("favorite")),
            consent=ConsentRecord.from_payload(payload.get("consent")),
            reference_asset=str(payload.get("reference_asset") or ""),
            prompt_asset=str(payload.get("prompt_asset") or ""),
            stable_sample=bool(payload.get("stable_sample")),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            capabilities=tuple(str(item) for item in payload.get("capabilities") or ()),
        )
