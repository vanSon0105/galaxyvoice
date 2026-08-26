from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TranscriptWord:
    word_id: str
    text: str
    start_ms: int
    end_ms: int
    confidence: float | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TranscriptWord":
        confidence = payload.get("confidence")
        return cls(
            word_id=str(payload.get("word_id") or uuid4().hex),
            text=str(payload.get("text") or "").strip(),
            start_ms=int(payload.get("start_ms") or 0),
            end_ms=int(payload.get("end_ms") or 0),
            confidence=float(confidence) if confidence is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "word_id": self.word_id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class TranscriptCue:
    cue_id: str
    position: int
    start_ms: int
    end_ms: int
    text: str
    speaker_id: str = "speaker-1"
    confidence: float | None = None
    words: tuple[TranscriptWord, ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TranscriptCue":
        confidence = payload.get("confidence")
        return cls(
            cue_id=str(payload.get("cue_id") or uuid4().hex),
            position=int(payload.get("position") or 0),
            start_ms=int(payload.get("start_ms") or 0),
            end_ms=int(payload.get("end_ms") or 0),
            text=str(payload.get("text") or "").strip(),
            speaker_id=str(payload.get("speaker_id") or "speaker-1"),
            confidence=float(confidence) if confidence is not None else None,
            words=tuple(
                TranscriptWord.from_dict(item)
                for item in payload.get("words", ())
                if isinstance(item, Mapping)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cue_id": self.cue_id,
            "position": self.position,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
            "speaker_id": self.speaker_id,
            "confidence": self.confidence,
            "words": [word.to_dict() for word in self.words],
        }


@dataclass(frozen=True)
class TranscriptSpeaker:
    speaker_id: str
    label: str
    color: str = "#d08ca1"
    reference_path: str = ""
    reference_start_ms: int | None = None
    reference_end_ms: int | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TranscriptSpeaker":
        start = payload.get("reference_start_ms")
        end = payload.get("reference_end_ms")
        return cls(
            speaker_id=str(payload.get("speaker_id") or uuid4().hex),
            label=str(payload.get("label") or "Người nói").strip(),
            color=str(payload.get("color") or "#d08ca1"),
            reference_path=str(payload.get("reference_path") or ""),
            reference_start_ms=int(start) if start is not None else None,
            reference_end_ms=int(end) if end is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker_id": self.speaker_id,
            "label": self.label,
            "color": self.color,
            "reference_path": self.reference_path,
            "reference_start_ms": self.reference_start_ms,
            "reference_end_ms": self.reference_end_ms,
        }


@dataclass(frozen=True)
class TranscriptProject:
    transcript_id: str
    project_id: str
    name: str
    status: str
    revision: int
    source_path: str
    source_kind: str
    requested_language: str
    detected_language: str
    model_id: str
    requested_device: str
    resolved_device: str
    diarization_requested: bool
    diarization_state: str
    created_at: str
    updated_at: str
    duration_ms: int = 0
    cue_count_hint: int = 0
    speakers: tuple[TranscriptSpeaker, ...] = ()
    cues: tuple[TranscriptCue, ...] = ()
    warnings: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    handoffs: tuple[Mapping[str, Any], ...] = ()

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        name: str,
        source_path: str,
        source_kind: str,
        requested_language: str,
        model_id: str,
        requested_device: str,
        diarization_requested: bool,
        cues: tuple[TranscriptCue, ...] = (),
        detected_language: str = "",
        status: str = "draft",
    ) -> "TranscriptProject":
        now = utc_now()
        duration_ms = max((cue.end_ms for cue in cues), default=0)
        return cls(
            transcript_id=uuid4().hex,
            project_id=project_id.strip(),
            name=name.strip() or "Transcript",
            status=status,
            revision=1,
            source_path=source_path.strip(),
            source_kind=source_kind,
            requested_language=requested_language.strip() or "auto",
            detected_language=detected_language.strip(),
            model_id=model_id.strip() or "base",
            requested_device=requested_device.strip() or "auto",
            resolved_device="",
            diarization_requested=diarization_requested,
            diarization_state="pending" if diarization_requested else "disabled",
            created_at=now,
            updated_at=now,
            duration_ms=duration_ms,
            cue_count_hint=len(cues),
            speakers=(TranscriptSpeaker("speaker-1", "Người nói 1"),),
            cues=normalize_cues(cues),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TranscriptProject":
        return cls(
            transcript_id=str(payload["transcript_id"]),
            project_id=str(payload.get("project_id") or ""),
            name=str(payload.get("name") or "Transcript"),
            status=str(payload.get("status") or "draft"),
            revision=max(1, int(payload.get("revision") or 1)),
            source_path=str(payload.get("source_path") or ""),
            source_kind=str(payload.get("source_kind") or "manual"),
            requested_language=str(payload.get("requested_language") or "auto"),
            detected_language=str(payload.get("detected_language") or ""),
            model_id=str(payload.get("model_id") or "base"),
            requested_device=str(payload.get("requested_device") or "auto"),
            resolved_device=str(payload.get("resolved_device") or ""),
            diarization_requested=bool(payload.get("diarization_requested", False)),
            diarization_state=str(payload.get("diarization_state") or "disabled"),
            created_at=str(payload.get("created_at") or utc_now()),
            updated_at=str(payload.get("updated_at") or utc_now()),
            duration_ms=max(0, int(payload.get("duration_ms") or 0)),
            cue_count_hint=max(0, int(payload.get("cue_count") or 0)),
            speakers=tuple(
                TranscriptSpeaker.from_dict(item)
                for item in payload.get("speakers", ())
                if isinstance(item, Mapping)
            ),
            cues=normalize_cues(
                tuple(
                    TranscriptCue.from_dict(item)
                    for item in payload.get("cues", ())
                    if isinstance(item, Mapping)
                )
            ),
            warnings=tuple(str(item) for item in payload.get("warnings", ())),
            provenance=dict(payload.get("provenance") or {}),
            handoffs=tuple(
                dict(item) for item in payload.get("handoffs", ()) if isinstance(item, Mapping)
            ),
        )

    def to_dict(self, *, include_cues: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "transcript_id": self.transcript_id,
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status,
            "revision": self.revision,
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "requested_language": self.requested_language,
            "detected_language": self.detected_language,
            "model_id": self.model_id,
            "requested_device": self.requested_device,
            "resolved_device": self.resolved_device,
            "diarization_requested": self.diarization_requested,
            "diarization_state": self.diarization_state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "duration_ms": self.duration_ms,
            "speakers": [speaker.to_dict() for speaker in self.speakers],
            "cue_count": max(len(self.cues), self.cue_count_hint),
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
            "handoffs": [dict(item) for item in self.handoffs],
        }
        if include_cues:
            payload["cues"] = [cue.to_dict() for cue in self.cues]
        return payload

    def evolved(self, **changes: Any) -> "TranscriptProject":
        if "cues" in changes and "duration_ms" not in changes:
            changes["duration_ms"] = max(
                (cue.end_ms for cue in changes["cues"]),
                default=0,
            )
        if "cues" in changes:
            changes["cue_count_hint"] = len(changes["cues"])
        return replace(self, revision=self.revision + 1, updated_at=utc_now(), **changes)


def normalize_cues(cues: tuple[TranscriptCue, ...]) -> tuple[TranscriptCue, ...]:
    ordered = sorted(cues, key=lambda cue: (cue.position, cue.start_ms, cue.end_ms))
    return tuple(replace(cue, position=index) for index, cue in enumerate(ordered))


def validate_project(project: TranscriptProject) -> None:
    if not project.transcript_id or not project.name.strip():
        raise ValueError("Transcript cần ID và tên.")
    if not project.project_id.strip():
        raise ValueError("Transcript phải thuộc một Galaxy Project.")
    speaker_ids = {speaker.speaker_id for speaker in project.speakers}
    if not speaker_ids:
        raise ValueError("Transcript cần ít nhất một người nói.")
    for cue in project.cues:
        if cue.start_ms < 0 or cue.end_ms <= cue.start_ms:
            raise ValueError(f"Mốc thời gian không hợp lệ ở cue {cue.position + 1}.")
        if not cue.text.strip():
            raise ValueError(f"Cue {cue.position + 1} chưa có nội dung.")
        if cue.speaker_id not in speaker_ids:
            raise ValueError(f"Cue {cue.position + 1} tham chiếu người nói không tồn tại.")
