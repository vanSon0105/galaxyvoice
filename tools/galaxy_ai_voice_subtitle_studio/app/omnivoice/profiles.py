from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..common.cache import read_json, write_json_atomic
from ..common.paths import slugify


PROFILE_FILE = "voice.pt"
METADATA_FILE = "profile.json"


@dataclass(frozen=True)
class PendingVoiceProfile:
    profile_id: str
    profile_dir: Path
    prompt_path: Path
    metadata_path: Path


@dataclass(frozen=True)
class VoiceProfile:
    profile_id: str
    display_name: str
    language: str
    prompt_path: Path
    reference_audio_path: Path | None
    reference_text: str
    created_at: str


def prepare_voice_profile(profiles_dir: Path, display_name: str) -> PendingVoiceProfile:
    name = display_name.strip()
    if not name:
        raise ValueError("Tên profile giọng không được để trống.")
    profiles_dir = Path(profiles_dir)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_id = slugify(name)
    profile_dir = profiles_dir / profile_id
    if profile_dir.exists():
        raise FileExistsError(f"Profile giọng đã tồn tại: {name}")
    profile_dir.mkdir(parents=False)
    return PendingVoiceProfile(
        profile_id=profile_id,
        profile_dir=profile_dir,
        prompt_path=profile_dir / PROFILE_FILE,
        metadata_path=profile_dir / METADATA_FILE,
    )


def finalize_voice_profile(
    pending: PendingVoiceProfile,
    *,
    display_name: str,
    language: str,
    reference_audio: Path | None,
    reference_text: str,
    source: str = "cloned",
    consent_confirmed: bool = False,
    consent_basis: str = "",
    consent_statement: str = "",
) -> VoiceProfile:
    if not pending.prompt_path.is_file():
        raise FileNotFoundError(f"Worker chưa tạo voice prompt: {pending.prompt_path}")

    copied_reference: Path | None = None
    if reference_audio is not None:
        reference_source = Path(reference_audio)
        if reference_source.is_file():
            copied_reference = pending.profile_dir / f"reference{reference_source.suffix.lower() or '.wav'}"
            shutil.copy2(reference_source, copied_reference)

    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "version": 1,
        "profile_id": pending.profile_id,
        "display_name": display_name.strip(),
        "language": language.strip() or "auto",
        "prompt_file": pending.prompt_path.name,
        "reference_audio_file": copied_reference.name if copied_reference else "",
        "reference_text": reference_text.strip(),
        "created_at": created_at,
        "source": source,
        "consent": {
            "confirmed": bool(consent_confirmed),
            "basis": consent_basis.strip(),
            "statement": consent_statement.strip(),
            "recorded_at": created_at if consent_confirmed else "",
            "provenance": str(reference_audio) if reference_audio else "",
        },
    }
    write_json_atomic(pending.metadata_path, payload)
    return VoiceProfile(
        profile_id=pending.profile_id,
        display_name=payload["display_name"],
        language=payload["language"],
        prompt_path=pending.prompt_path,
        reference_audio_path=copied_reference,
        reference_text=payload["reference_text"],
        created_at=created_at,
    )


def list_voice_profiles(profiles_dir: Path) -> list[VoiceProfile]:
    profiles_dir = Path(profiles_dir)
    if not profiles_dir.is_dir():
        return []
    profiles: list[VoiceProfile] = []
    for metadata_path in profiles_dir.glob(f"*/{METADATA_FILE}"):
        payload = read_json(metadata_path)
        if not isinstance(payload, dict):
            continue
        prompt_path = metadata_path.parent / str(payload.get("prompt_file") or PROFILE_FILE)
        if not prompt_path.is_file():
            continue
        reference_name = str(payload.get("reference_audio_file") or "")
        reference_path = metadata_path.parent / reference_name if reference_name else None
        profiles.append(
            VoiceProfile(
                profile_id=str(payload.get("profile_id") or metadata_path.parent.name),
                display_name=str(payload.get("display_name") or metadata_path.parent.name),
                language=str(payload.get("language") or "auto"),
                prompt_path=prompt_path,
                reference_audio_path=(
                    reference_path if reference_path is not None and reference_path.is_file() else None
                ),
                reference_text=str(payload.get("reference_text") or ""),
                created_at=str(payload.get("created_at") or ""),
            )
        )
    return sorted(profiles, key=lambda profile: (profile.display_name.casefold(), profile.profile_id))


def find_voice_profile(profiles_dir: Path, profile_id: str) -> VoiceProfile | None:
    return next(
        (profile for profile in list_voice_profiles(profiles_dir) if profile.profile_id == profile_id),
        None,
    )


def delete_voice_profile(profiles_dir: Path, profile_id: str) -> None:
    profiles_root = Path(profiles_dir).resolve()
    profile_dir = (profiles_root / profile_id).resolve()
    if profile_dir.parent != profiles_root:
        raise ValueError("Đường dẫn profile không hợp lệ.")
    if profile_dir.is_dir():
        shutil.rmtree(profile_dir)


def discard_pending_profile(pending: PendingVoiceProfile | None) -> None:
    if pending is not None and pending.profile_dir.is_dir():
        shutil.rmtree(pending.profile_dir, ignore_errors=True)
