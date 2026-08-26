from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...common.config import default_config_path
from ...omnivoice.profiles import list_voice_profiles
from ...omnivoice.runtime import OmniVoiceRuntime
from ...voice.tts import create_tts_engine, tts_engine_codes
from ...voice_library.models import VoiceProfileRecord, VoiceSelection
from ...voice_library.repository import VoiceLibraryRepository
from ...voice_library.service import VoiceInUseError, VoiceLibraryService
from ..event_bus import event_bus


router = APIRouter(prefix="/api/voice-library", tags=["voice-library"])


def _settings_path(request: Request) -> Path:
    path = getattr(request.app.state, "settings_path", None)
    return Path(path) if path is not None else default_config_path()


def _library_dir(request: Request) -> Path:
    return _settings_path(request).with_name("voice_library")


def _profiles_dir() -> Path:
    return OmniVoiceRuntime.default().profiles_dir


def _service(request: Request) -> VoiceLibraryService:
    return VoiceLibraryService(
        VoiceLibraryRepository(_library_dir(request)),
        _profiles_dir(),
        _settings_path(request).parent,
    )


def _system_voices() -> list[VoiceProfileRecord]:
    records: list[VoiceProfileRecord] = []
    for engine_code in tts_engine_codes():
        engine = create_tts_engine(engine_code)
        try:
            voices = engine.list_voices() if engine_code == "sapi" else engine.initial_voices()
        except (OSError, RuntimeError, ValueError):
            voices = engine.initial_voices()
        for voice in voices:
            records.append(
                VoiceProfileRecord(
                    voice_id=f"system:{engine_code}:{voice.name}",
                    revision=1,
                    name=voice.name,
                    source="system",
                    language=voice.culture or "auto",
                    engine_id=engine_code,
                    selection=VoiceSelection(
                        source="system",
                        system_engine=engine_code,
                        system_voice=voice.name,
                    ),
                    notes=", ".join(part for part in (voice.gender, voice.age) if part),
                    capabilities=(f"{engine_code}.tts",),
                )
            )
    return records


def _records(request: Request) -> tuple[VoiceProfileRecord, ...]:
    return _service(request).list_voices(list_voice_profiles(_profiles_dir()), _system_voices())


def _find(request: Request, voice_id: str) -> VoiceProfileRecord:
    try:
        return _service(request).get(voice_id, list_voice_profiles(_profiles_dir()), _system_voices())
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Không tìm thấy giọng trong thư viện.") from error


def _voice_dict(record: VoiceProfileRecord, request: Request) -> dict[str, Any]:
    data = record.to_payload()
    data.update(
        {
            "preview_available": bool(record.reference_asset and Path(record.reference_asset).is_file()),
            "preview_url": f"/api/voice-library/voices/{record.voice_id}/preview",
            "usage_count": len(_service(request).usage(record.voice_id)),
            "editable": True,
            "identity_editable": record.source != "system",
            "deletable": record.source != "system",
            "compatibility": {
                "studio": record.selection.source in {"profile", "reference", "design"},
                "batch": record.selection.source in {"profile", "reference", "design"},
                "longform": record.selection.source == "profile",
                "dubbing": record.selection.source == "profile",
            },
        }
    )
    return data


@router.get("/voices")
def list_voices(
    request: Request,
    query: str = "",
    source: str = "",
    language: str = "",
    favorite_only: bool = False,
) -> list[dict[str, Any]]:
    records = _service(request).list_voices(
        list_voice_profiles(_profiles_dir()),
        _system_voices(),
        query=query,
        source=source,
        language=language,
        favorite_only=favorite_only,
    )
    return [_voice_dict(item, request) for item in records]


class ConsentRequest(BaseModel):
    confirmed: bool = False
    basis: str = ""
    statement: str = ""
    provenance: str = ""


class ImportAudioRequest(BaseModel):
    name: str = ""
    source: str = "imported"
    language: str = "auto"
    audio_path: str
    reference_text: str = ""
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    consent: ConsentRequest = Field(default_factory=ConsentRequest)


@router.post("/voices/import-audio")
def import_audio(body: ImportAudioRequest, request: Request) -> dict[str, Any]:
    try:
        item = _service(request).import_audio(
            name=body.name,
            source=body.source,
            language=body.language,
            audio_path=Path(body.audio_path),
            reference_text=body.reference_text,
            tags=body.tags,
            notes=body.notes,
            consent_payload=body.consent.model_dump(),
        )
    except (ValueError, FileNotFoundError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _emit(item.voice_id)
    return _voice_dict(item, request)


class DesignRequest(BaseModel):
    name: str = ""
    language: str = "auto"
    instruction: str
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


@router.post("/voices/design")
def create_design(body: DesignRequest, request: Request) -> dict[str, Any]:
    try:
        item = _service(request).create_design(
            name=body.name,
            language=body.language,
            instruction=body.instruction,
            tags=body.tags,
            notes=body.notes,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _emit(item.voice_id)
    return _voice_dict(item, request)


class BundleImportRequest(BaseModel):
    bundle_path: str


@router.post("/import")
def import_bundle(body: BundleImportRequest, request: Request) -> dict[str, Any]:
    try:
        item = _service(request).import_bundle(Path(body.bundle_path))
    except (ValueError, FileNotFoundError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _emit(item.voice_id)
    return _voice_dict(item, request)


class UpdateVoiceRequest(BaseModel):
    name: str | None = None
    language: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    favorite: bool | None = None
    consent: ConsentRequest | None = None


@router.patch("/voices/{voice_id}")
def update_voice(voice_id: str, body: UpdateVoiceRequest, request: Request) -> dict[str, Any]:
    current = _find(request, voice_id)
    changes = body.model_dump(exclude_none=True)
    try:
        item = _service(request).update(current, changes)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _emit(item.voice_id)
    return _voice_dict(item, request)


@router.get("/voices/{voice_id}/preview")
def preview(voice_id: str, request: Request) -> FileResponse:
    item = _find(request, voice_id)
    path = Path(item.reference_asset) if item.reference_asset else None
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Giọng này chưa có audio xem trước.")
    return FileResponse(path, filename=f"{item.name}{path.suffix.lower()}")


@router.get("/voices/{voice_id}/usage")
def usage(voice_id: str, request: Request) -> dict[str, Any]:
    _find(request, voice_id)
    usages = _service(request).usage(voice_id)
    return {"voice_id": voice_id, "count": len(usages), "items": usages}


class StableSampleRequest(BaseModel):
    audio_path: str
    reference_text: str = ""


@router.post("/voices/{voice_id}/stable-sample")
def stable_sample(voice_id: str, body: StableSampleRequest, request: Request) -> dict[str, Any]:
    current = _find(request, voice_id)
    if current.source not in {"cloned", "imported"}:
        raise HTTPException(status_code=422, detail="Chỉ giọng nhập hoặc giọng nhái mới có mẫu ổn định.")
    try:
        item = _service(request).set_stable_sample(current, Path(body.audio_path), body.reference_text)
    except (FileNotFoundError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _emit(item.voice_id)
    return _voice_dict(item, request)


class PinRequest(BaseModel):
    project_id: str


@router.post("/voices/{voice_id}/pin")
def pin(voice_id: str, body: PinRequest, request: Request) -> dict[str, Any]:
    try:
        return _service(request).pin(_find(request, voice_id), body.project_id)
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class ExportRequest(BaseModel):
    output_path: str


@router.post("/voices/{voice_id}/export")
def export(voice_id: str, body: ExportRequest, request: Request) -> dict[str, str]:
    try:
        path = _service(request).export_bundle(_find(request, voice_id), Path(body.output_path))
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"path": str(path)}


@router.delete("/voices/{voice_id}")
def delete(voice_id: str, request: Request, force: bool = Query(False)) -> dict[str, bool]:
    current = _find(request, voice_id)
    if current.source == "system":
        raise HTTPException(status_code=422, detail="Không thể xóa giọng do hệ thống cung cấp.")
    try:
        _service(request).delete(current, force=force)
    except VoiceInUseError as error:
        raise HTTPException(status_code=409, detail={"message": str(error), "usages": error.usages}) from error
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _emit(voice_id)
    return {"ok": True}


def _emit(voice_id: str) -> None:
    event_bus.emit({"type": "event", "kind": "voice_library_updated", "payload": {"voice_id": voice_id}})
