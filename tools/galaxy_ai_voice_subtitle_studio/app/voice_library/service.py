from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable
from uuid import uuid4

from ..common.cache import read_json, write_json_atomic
from ..omnivoice.profiles import (
    VoiceProfile,
    delete_voice_profile,
    discard_pending_profile,
    finalize_voice_profile,
    prepare_voice_profile,
)
from .models import ConsentRecord, VoiceProfileRecord, VoiceSelection
from .repository import VoiceLibraryRepository


BUNDLE_FORMAT = "galaxy.voice-profile"
BUNDLE_VERSION = 1


class VoiceInUseError(RuntimeError):
    def __init__(self, usages: list[dict[str, str]]) -> None:
        super().__init__("Giọng đang được dùng. Hãy xem nơi sử dụng trước khi xóa.")
        self.usages = usages


class VoiceLibraryService:
    def __init__(self, repository: VoiceLibraryRepository, profiles_dir: Path, settings_dir: Path) -> None:
        self.repository = repository
        self.profiles_dir = Path(profiles_dir)
        self.settings_dir = Path(settings_dir)

    def list_voices(
        self,
        profiles: Iterable[VoiceProfile],
        system_voices: Iterable[VoiceProfileRecord] = (),
        *,
        query: str = "",
        source: str = "",
        language: str = "",
        favorite_only: bool = False,
    ) -> tuple[VoiceProfileRecord, ...]:
        local = {item.voice_id: item for item in self.repository.list()}
        for profile in profiles:
            voice_id = f"omnivoice:{profile.profile_id}"
            metadata = read_json(profile.prompt_path.parent / "profile.json")
            metadata = metadata if isinstance(metadata, dict) else {}
            existing = local.get(voice_id)
            consent = existing.consent if existing else ConsentRecord.from_payload(metadata.get("consent"))
            source_name = str(metadata.get("source") or "cloned")
            if source_name not in {"cloned", "designed"}:
                source_name = "cloned"
            record = VoiceProfileRecord(
                voice_id=voice_id,
                revision=existing.revision if existing else 1,
                name=existing.name if existing else profile.display_name,
                source=source_name,
                language=existing.language if existing else profile.language,
                engine_id="omnivoice",
                selection=VoiceSelection(source="profile", profile_id=profile.profile_id),
                tags=existing.tags if existing else (),
                notes=existing.notes if existing else "",
                favorite=existing.favorite if existing else False,
                consent=consent,
                reference_asset=(existing.reference_asset if existing and existing.stable_sample else str(profile.reference_audio_path or "")),
                prompt_asset=str(profile.prompt_path),
                stable_sample=bool(existing.stable_sample if existing else profile.reference_audio_path),
                created_at=existing.created_at if existing else profile.created_at,
                updated_at=existing.updated_at if existing else profile.created_at,
                capabilities=(
                    tuple(dict.fromkeys(("omnivoice.profile", *existing.capabilities, "preview")))
                    if existing and existing.stable_sample
                    else ("omnivoice.profile", "preview") if profile.reference_audio_path else ("omnivoice.profile",)
                ),
            )
            local[voice_id] = record

        for record in system_voices:
            existing = local.get(record.voice_id)
            if existing:
                record = replace(
                    record,
                    revision=existing.revision,
                    tags=existing.tags,
                    notes=existing.notes,
                    favorite=existing.favorite,
                    created_at=existing.created_at,
                    updated_at=existing.updated_at,
                )
            local[record.voice_id] = record

        needle = query.strip().casefold()
        source_filter = source.strip().casefold()
        lang = language.strip().casefold()
        return tuple(
            sorted(
                (
                    item
                    for item in local.values()
                    if (not needle or needle in f"{item.name} {item.notes} {' '.join(item.tags)}".casefold())
                    and (not source_filter or item.source == source_filter)
                    and (not lang or item.language.casefold() == lang)
                    and (not favorite_only or item.favorite)
                ),
                key=lambda item: (not item.favorite, item.name.casefold(), item.voice_id),
            )
        )

    def get(self, voice_id: str, profiles: Iterable[VoiceProfile], system_voices: Iterable[VoiceProfileRecord] = ()) -> VoiceProfileRecord:
        item = next((voice for voice in self.list_voices(profiles, system_voices) if voice.voice_id == voice_id), None)
        if item is None:
            raise KeyError(voice_id)
        return item

    def update(self, current: VoiceProfileRecord, changes: dict[str, object]) -> VoiceProfileRecord:
        now = _now()
        tags_value = changes.get("tags", current.tags)
        tags = tuple(dict.fromkeys(str(item).strip() for item in tags_value if str(item).strip())) if isinstance(tags_value, (list, tuple)) else current.tags
        consent = current.consent
        if isinstance(changes.get("consent"), dict):
            consent = _consent(changes["consent"], required=current.source == "cloned")
        updated = replace(
            current,
            name=(str(changes.get("name", current.name)).strip() or current.name) if current.source != "system" else current.name,
            language=(str(changes.get("language", current.language)).strip() or current.language) if current.source != "system" else current.language,
            tags=tags,
            notes=str(changes.get("notes", current.notes)).strip(),
            favorite=bool(changes.get("favorite", current.favorite)),
            consent=consent,
            updated_at=now,
        )
        return self.repository.save(updated)

    def import_audio(
        self,
        *,
        name: str,
        source: str,
        language: str,
        audio_path: Path,
        reference_text: str,
        tags: Iterable[str],
        notes: str,
        consent_payload: object,
    ) -> VoiceProfileRecord:
        source_name = source.strip().lower()
        if source_name not in {"imported", "cloned"}:
            raise ValueError("Nguồn audio phải là imported hoặc cloned.")
        consent = _consent(consent_payload, required=source_name == "cloned")
        source_path = Path(audio_path).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Không tìm thấy audio mẫu: {source_path}")
        if source_path.suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}:
            raise ValueError("Audio mẫu phải là WAV, MP3, M4A, FLAC, OGG hoặc AAC.")
        voice_id = f"local:{uuid4().hex}"
        voice_dir = self.repository.assets_dir / voice_id.split(":", 1)[1]
        voice_dir.mkdir(parents=True, exist_ok=False)
        managed = voice_dir / f"reference{source_path.suffix.lower()}"
        shutil.copy2(source_path, managed)
        now = _now()
        record = VoiceProfileRecord(
            voice_id=voice_id,
            revision=1,
            name=name.strip() or source_path.stem,
            source=source_name,
            language=language.strip() or "auto",
            engine_id="omnivoice",
            selection=VoiceSelection(source="reference", reference_audio=str(managed), reference_text=reference_text.strip()),
            tags=tuple(dict.fromkeys(item.strip() for item in tags if item.strip())),
            notes=notes.strip(),
            consent=consent,
            reference_asset=str(managed),
            stable_sample=True,
            created_at=now,
            updated_at=now,
            capabilities=("omnivoice.reference", "preview"),
        )
        return self.repository.save(record)

    def create_design(self, *, name: str, language: str, instruction: str, tags: Iterable[str], notes: str) -> VoiceProfileRecord:
        if not instruction.strip():
            raise ValueError("Hãy mô tả giọng cần thiết kế.")
        now = _now()
        record = VoiceProfileRecord(
            voice_id=f"design:{uuid4().hex}",
            revision=1,
            name=name.strip() or "Designed voice",
            source="designed",
            language=language.strip() or "auto",
            engine_id="omnivoice",
            selection=VoiceSelection(source="design", instruction=instruction.strip()),
            tags=tuple(dict.fromkeys(item.strip() for item in tags if item.strip())),
            notes=notes.strip(),
            created_at=now,
            updated_at=now,
            capabilities=("omnivoice.design",),
        )
        return self.repository.save(record)

    def set_stable_sample(self, current: VoiceProfileRecord, audio_path: Path, reference_text: str) -> VoiceProfileRecord:
        source = Path(audio_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        voice_dir = self.repository.assets_dir / _safe_id(current.voice_id)
        voice_dir.mkdir(parents=True, exist_ok=True)
        managed = voice_dir / f"stable{source.suffix.lower() or '.wav'}"
        shutil.copy2(source, managed)
        selection = current.selection
        if current.selection.source != "profile":
            selection = replace(
                current.selection,
                source="reference",
                profile_id="",
                reference_audio=str(managed),
                reference_text=reference_text.strip(),
            )
        return self.repository.save(replace(current, selection=selection, reference_asset=str(managed), stable_sample=True, updated_at=_now(), capabilities=tuple(dict.fromkeys((*current.capabilities, "preview", "omnivoice.reference")))))

    def usage(self, voice_id: str) -> list[dict[str, str]]:
        tokens = {voice_id}
        if ":" in voice_id:
            tokens.add(voice_id.split(":", 1)[1])
        usages: list[dict[str, str]] = []
        candidates = {
            "Studio": self.settings_dir / "studio_takes.json",
            "Batch": self.settings_dir / "batch_runs.json",
            "Workspace": self.settings_dir / "omnivoice_workspaces.json",
        }
        for label, path in candidates.items():
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                if any(f'"{token}"' in text for token in tokens):
                    usages.append({"kind": label.lower(), "label": label, "path": str(path)})
        pin_root = self.repository.pins_dir
        if pin_root.is_dir():
            for snapshot in pin_root.glob("*/voices/*/snapshot.json"):
                data = read_json(snapshot)
                if isinstance(data, dict) and data.get("voice_id") == voice_id:
                    usages.append({"kind": "project", "label": f"Project {snapshot.parents[2].name}", "path": str(snapshot)})
        return usages

    def delete(self, current: VoiceProfileRecord, *, force: bool = False) -> None:
        usages = self.usage(current.voice_id)
        if usages and not force:
            raise VoiceInUseError(usages)
        self.repository.delete(current.voice_id)
        if current.voice_id.startswith("omnivoice:"):
            delete_voice_profile(self.profiles_dir, current.voice_id.split(":", 1)[1])
        for asset in (current.reference_asset, current.prompt_asset):
            path = Path(asset) if asset else None
            if path and _is_within(path, self.repository.assets_dir):
                shutil.rmtree(path.parent, ignore_errors=True)

    def pin(self, current: VoiceProfileRecord, project_id: str) -> dict[str, str | int]:
        project = project_id.strip()
        if not project:
            raise ValueError("Chưa chọn dự án để ghim giọng.")
        target = self.repository.pins_dir / _safe_id(project) / "voices" / _safe_id(current.voice_id)
        target.mkdir(parents=True, exist_ok=True)
        assets: dict[str, str] = {}
        for key, raw_path in (("reference", current.reference_asset), ("prompt", current.prompt_asset)):
            source = Path(raw_path) if raw_path else None
            if source and source.is_file():
                destination = target / f"{key}{source.suffix.lower()}"
                shutil.copy2(source, destination)
                assets[key] = destination.name
        digest = hashlib.sha256(json.dumps(current.to_payload(), sort_keys=True).encode("utf-8")).hexdigest()
        snapshot = {
            "version": 1,
            "project_id": project,
            "voice_id": current.voice_id,
            "voice_revision": current.revision,
            "fingerprint": digest,
            "voice": current.to_payload(),
            "assets": assets,
            "pinned_at": _now(),
        }
        path = target / "snapshot.json"
        write_json_atomic(path, snapshot)
        return {"project_id": project, "voice_id": current.voice_id, "revision": current.revision, "snapshot_path": str(path)}

    def export_bundle(self, current: VoiceProfileRecord, output_path: Path) -> Path:
        if current.source == "system":
            raise ValueError("Giọng hệ thống không thể đóng gói; hãy cài cùng engine trên máy đích.")
        if current.source == "cloned" and not current.consent.confirmed:
            raise ValueError("Giọng nhái chưa có xác nhận quyền sử dụng nên không thể xuất bundle.")
        destination = Path(output_path).expanduser()
        if destination.suffix.lower() != ".galaxyvoice":
            destination = destination.with_suffix(".galaxyvoice")
        destination.parent.mkdir(parents=True, exist_ok=True)
        voice_payload = current.to_payload()
        voice_payload["selection"]["reference_audio"] = ""
        voice_payload["reference_asset"] = ""
        voice_payload["prompt_asset"] = ""
        manifest = {"format": BUNDLE_FORMAT, "version": BUNDLE_VERSION, "exported_at": _now(), "voice": voice_payload, "assets": {}}
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for key, raw_path in (("reference", current.reference_asset), ("prompt", current.prompt_asset)):
                source = Path(raw_path) if raw_path else None
                if source and source.is_file():
                    name = f"assets/{key}{source.suffix.lower()}"
                    archive.write(source, name)
                    manifest["assets"][key] = name
            archive.writestr("voice.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return destination

    def import_bundle(self, bundle_path: Path) -> VoiceProfileRecord:
        bundle = Path(bundle_path).expanduser().resolve()
        if not bundle.is_file():
            raise FileNotFoundError(bundle)
        with zipfile.ZipFile(bundle) as archive:
            _validate_archive(archive)
            try:
                manifest = json.loads(archive.read("voice.json"))
            except (KeyError, json.JSONDecodeError) as error:
                raise ValueError("Bundle giọng thiếu voice.json hợp lệ.") from error
            if manifest.get("format") != BUNDLE_FORMAT or int(manifest.get("version") or 0) != BUNDLE_VERSION:
                raise ValueError("Định dạng bundle giọng không được hỗ trợ.")
            record = VoiceProfileRecord.from_payload(manifest.get("voice") or {})
            if record.source == "cloned" and not record.consent.confirmed:
                raise ValueError("Bundle giọng nhái thiếu xác nhận quyền sử dụng.")
            new_id = f"{record.source}:{uuid4().hex}"
            target = self.repository.assets_dir / _safe_id(new_id)
            target.mkdir(parents=True, exist_ok=False)
            assets = manifest.get("assets") if isinstance(manifest.get("assets"), dict) else {}
            reference = _extract_asset(archive, assets.get("reference"), target, "reference")
            prompt = _extract_asset(archive, assets.get("prompt"), target, "prompt")

        if prompt:
            return self._install_prompt_profile(record, reference, prompt, target)

        selection = replace(record.selection, reference_audio=str(reference or ""), profile_id="")
        capabilities = tuple(cap for cap in record.capabilities if cap != "omnivoice.profile")
        if reference:
            selection = replace(selection, source="reference")
            capabilities = tuple(dict.fromkeys((*capabilities, "omnivoice.reference", "preview")))
        elif record.source == "designed":
            selection = replace(selection, source="design")
        now = _now()
        imported = replace(record, voice_id=new_id, revision=1, selection=selection, reference_asset=str(reference or ""), prompt_asset=str(prompt or ""), created_at=now, updated_at=now, capabilities=capabilities)
        return self.repository.save(imported)

    def _install_prompt_profile(
        self,
        record: VoiceProfileRecord,
        reference: Path | None,
        prompt: Path,
        extracted_dir: Path,
    ) -> VoiceProfileRecord:
        pending = prepare_voice_profile(
            self.profiles_dir,
            f"{record.name}-imported-{uuid4().hex[:8]}",
        )
        try:
            shutil.copy2(prompt, pending.prompt_path)
            profile = finalize_voice_profile(
                pending,
                display_name=record.name,
                language=record.language,
                reference_audio=reference,
                reference_text=record.selection.reference_text,
                source="designed" if record.source == "designed" else "cloned",
                consent_confirmed=record.consent.confirmed,
                consent_basis=record.consent.basis,
                consent_statement=record.consent.statement,
            )
        except Exception:
            discard_pending_profile(pending)
            raise
        finally:
            shutil.rmtree(extracted_dir, ignore_errors=True)

        now = _now()
        capabilities = tuple(dict.fromkeys((*record.capabilities, "omnivoice.profile")))
        if profile.reference_audio_path:
            capabilities = tuple(dict.fromkeys((*capabilities, "preview")))
        imported = replace(
            record,
            voice_id=f"omnivoice:{profile.profile_id}",
            revision=1,
            source="designed" if record.source == "designed" else "cloned",
            selection=VoiceSelection(source="profile", profile_id=profile.profile_id),
            reference_asset=str(profile.reference_audio_path or ""),
            prompt_asset=str(profile.prompt_path),
            created_at=now,
            updated_at=now,
            capabilities=capabilities,
        )
        return self.repository.save(imported)


def _consent(payload: object, *, required: bool) -> ConsentRecord:
    record = ConsentRecord.from_payload(payload)
    if required and not record.confirmed:
        raise ValueError("Phải xác nhận quyền sử dụng giọng nói trước khi lưu giọng nhái.")
    if record.confirmed and not record.recorded_at:
        record = replace(record, recorded_at=_now())
    return record


def _validate_archive(archive: zipfile.ZipFile) -> None:
    total = 0
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise ValueError("Bundle giọng chứa đường dẫn không an toàn.")
        total += info.file_size
        if total > 512 * 1024 * 1024:
            raise ValueError("Bundle giọng vượt quá giới hạn 512 MiB.")


def _extract_asset(archive: zipfile.ZipFile, name: object, target: Path, stem: str) -> Path | None:
    if not isinstance(name, str) or not name:
        return None
    suffix = PurePosixPath(name).suffix.lower()
    destination = target / f"{stem}{suffix}"
    try:
        with archive.open(name) as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)
    except KeyError as error:
        raise ValueError(f"Bundle giọng thiếu asset đã khai báo: {name}") from error
    return destination


def _safe_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
