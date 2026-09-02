"""Read-only VoiceStudio migration rehearsal over copied local data."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import stat
import subprocess
import wave
import zipfile
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any, Callable, Literal
from urllib.parse import quote

from ..common.ffmpeg import find_ffprobe
from ..common.paths import repository_root
from ..voice_library.models import ConsentRecord, VoiceProfileRecord
from .archive_policy import (
    ArchivePolicy,
    copy_archive_member,
    validate_archive_members,
)
from .models import SourceFingerprint
from .security import fingerprint_source, redact_report_value, resolve_approved_path


MAX_JSON_BYTES = 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 512
MAX_COMPRESSION_RATIO = 200

AssetState = Literal["managed", "linked", "missing", "unsafe"]
MigrationSourceKind = Literal["directory", "sqlite", "persona_bundle"]

_MEDIA_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}
_BUNDLE_SUFFIXES = {".ovsvoice", ".omnivoice"}
_UNSUPPORTED_TABLES = {
    "analytics",
    "analytics_events",
    "credentials",
    "job_events",
    "jobs",
    "marketplace_state",
    "mcp_client_bindings",
    "settings",
    "tokens",
}
_KNOWN_COLUMNS: dict[str, tuple[str, ...]] = {
    "voice_profiles": (
        "id",
        "name",
        "ref_audio_path",
        "ref_text",
        "instruct",
        "language",
        "locked_audio_path",
        "seed",
        "is_locked",
        "personality",
        "description",
        "is_demo",
        "verified_own_voice",
        "consent_text",
        "consent_audio_path",
        "consent_recorded_at",
        "kind",
        "vd_states",
        "created_at",
    ),
    "generation_history": (
        "id",
        "text",
        "mode",
        "language",
        "instruct",
        "profile_id",
        "audio_path",
        "duration_seconds",
        "generation_time",
        "seed",
        "starred",
        "created_at",
    ),
    "dub_history": (
        "id",
        "filename",
        "duration",
        "segments_count",
        "language",
        "language_code",
        "tracks",
        "job_data",
        "content_hash",
        "created_at",
    ),
    "studio_projects": (
        "id",
        "name",
        "video_path",
        "audio_path",
        "duration",
        "state_json",
        "created_at",
        "updated_at",
    ),
    "export_history": (
        "id",
        "filename",
        "destination_path",
        "mode",
        "created_at",
    ),
    "glossary_terms": (
        "id",
        "project_id",
        "source",
        "target",
        "note",
        "auto",
        "created_at",
    ),
    "pronunciation_entries": (
        "id",
        "term",
        "replacement",
        "type",
        "language",
        "enabled",
        "created_at",
    ),
}
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)


@dataclass(frozen=True)
class MigrationAsset:
    role: str
    hint: str
    state: AssetState
    expected_sha256: str = ""
    byte_size: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _text(redact_report_value(self.role)))
        object.__setattr__(self, "hint", _text(redact_report_value(self.hint)))
        object.__setattr__(
            self,
            "expected_sha256",
            _text(redact_report_value(self.expected_sha256)),
        )


@dataclass(frozen=True)
class MigrationCandidate:
    source_id: str
    target: str
    data: Mapping[str, Any] = field(default_factory=dict)
    assets: tuple[MigrationAsset, ...] = ()
    warnings: tuple[str, ...] = ()
    consent: ConsentRecord = field(default_factory=ConsentRecord)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_id",
            _text(redact_report_value(self.source_id)),
        )
        object.__setattr__(self, "target", _text(redact_report_value(self.target)))
        safe_data = redact_report_value(dict(self.data))
        safe_consent = redact_report_value(asdict(self.consent))
        object.__setattr__(self, "data", MappingProxyType(dict(safe_data)))
        object.__setattr__(self, "assets", tuple(self.assets))
        object.__setattr__(
            self,
            "warnings",
            tuple(_text(redact_report_value(item)) for item in self.warnings),
        )
        object.__setattr__(self, "consent", ConsentRecord(**safe_consent))


@dataclass(frozen=True)
class MigrationFinding:
    source: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _text(redact_report_value(self.source)))
        object.__setattr__(self, "reason", _text(redact_report_value(self.reason)))


@dataclass(frozen=True)
class MigrationDryRun:
    source_before: SourceFingerprint
    source_after: SourceFingerprint
    voice_profiles: tuple[MigrationCandidate, ...] = ()
    persona_bundles: tuple[MigrationCandidate, ...] = ()
    generation_history: tuple[MigrationCandidate, ...] = ()
    dub_history: tuple[MigrationCandidate, ...] = ()
    studio_projects: tuple[MigrationCandidate, ...] = ()
    export_history: tuple[MigrationCandidate, ...] = ()
    glossary_terms: tuple[MigrationCandidate, ...] = ()
    pronunciation_entries: tuple[MigrationCandidate, ...] = ()
    discovered_documents: tuple[MigrationCandidate, ...] = ()
    assets: tuple[MigrationAsset, ...] = ()
    unsupported: tuple[MigrationFinding, ...] = ()
    warnings: tuple[str, ...] = ()
    sandbox_cleaned: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "warnings",
            tuple(_text(redact_report_value(item)) for item in self.warnings),
        )


class SourceChangedError(RuntimeError):
    """Raised when source bytes change during a read-only rehearsal."""


@dataclass(frozen=True)
class _MigrationSourceSelection:
    path: Path
    kind: MigrationSourceKind


@dataclass
class _Inspection:
    voice_profiles: list[MigrationCandidate] = field(default_factory=list)
    persona_bundles: list[MigrationCandidate] = field(default_factory=list)
    generation_history: list[MigrationCandidate] = field(default_factory=list)
    dub_history: list[MigrationCandidate] = field(default_factory=list)
    studio_projects: list[MigrationCandidate] = field(default_factory=list)
    export_history: list[MigrationCandidate] = field(default_factory=list)
    glossary_terms: list[MigrationCandidate] = field(default_factory=list)
    pronunciation_entries: list[MigrationCandidate] = field(default_factory=list)
    discovered_documents: list[MigrationCandidate] = field(default_factory=list)
    assets: list[MigrationAsset] = field(default_factory=list)
    unsupported: list[MigrationFinding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    check_cancelled: Callable[[], None] = field(default=lambda: None, repr=False)


def inspect_migration_source(
    source: Path,
    *,
    approved_roots: Sequence[Path],
    copied_source_confirmed: bool,
    sandbox_root: Path | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> MigrationDryRun:
    """Inspect a copied database, data directory, or persona bundle without writes."""

    if copied_source_confirmed is not True:
        raise ValueError("Explicit copied source confirmation is required")
    cancel = check_cancelled or (lambda: None)
    cancel()
    selection = _select_migration_source(Path(source), approved_roots)
    resolved_source = selection.path
    before = fingerprint_source(resolved_source, check_cancelled=cancel)
    approved = tuple(Path(root).expanduser().resolve(strict=False) for root in approved_roots)
    inspection = _Inspection(check_cancelled=cancel)

    sandbox_parent = None
    if sandbox_root is not None:
        sandbox_parent = Path(sandbox_root).expanduser().resolve(strict=False)
        if resolved_source.is_dir() and _is_within(sandbox_parent, resolved_source):
            raise ValueError("Sandbox root cannot be inside the inspected source directory")
        sandbox_parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(dir=sandbox_parent) as temporary:
        cancel()
        sandbox = Path(temporary)
        if selection.kind == "directory":
            _inspect_directory(resolved_source, approved, sandbox, inspection)
        elif selection.kind == "persona_bundle":
            _inspect_bundle(resolved_source, sandbox, inspection)
        elif selection.kind == "sqlite":
            _inspect_database(resolved_source, resolved_source.parent, approved, inspection)
        _validate_normalized_candidates(sandbox, inspection)
    sandbox_cleaned = not sandbox.exists()

    if selection.kind == "sqlite":
        _reject_sqlite_sidecars(resolved_source)
    cancel()
    after = fingerprint_source(resolved_source, check_cancelled=cancel)
    if after != before:
        raise SourceChangedError("Migration source changed during read-only inspection")

    return MigrationDryRun(
        source_before=before,
        source_after=after,
        voice_profiles=tuple(inspection.voice_profiles),
        persona_bundles=tuple(inspection.persona_bundles),
        generation_history=tuple(inspection.generation_history),
        dub_history=tuple(inspection.dub_history),
        studio_projects=tuple(inspection.studio_projects),
        export_history=tuple(inspection.export_history),
        glossary_terms=tuple(inspection.glossary_terms),
        pronunciation_entries=tuple(inspection.pronunciation_entries),
        discovered_documents=tuple(inspection.discovered_documents),
        assets=tuple(inspection.assets),
        unsupported=tuple(inspection.unsupported),
        warnings=tuple(inspection.warnings),
        sandbox_cleaned=sandbox_cleaned,
    )


def _select_migration_source(
    source: Path,
    approved_roots: Sequence[Path],
) -> _MigrationSourceSelection:
    requested = source.expanduser().absolute()
    try:
        requested_info = requested.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(f"Migration source does not exist: {source}") from None
    if _is_link_like(requested_info):
        raise ValueError("Migration source cannot be a top-level link or reparse point")
    resolved = resolve_approved_path(requested, approved_roots)
    _reject_live_or_protected_source(resolved)
    if resolved.is_dir():
        database = resolved / "omnivoice.db"
        if not _is_sqlite_file(database):
            raise ValueError(
                "Copied VoiceStudio directory must contain a readable omnivoice.db"
            )
        return _MigrationSourceSelection(resolved, "directory")
    if resolved.suffix.casefold() in _BUNDLE_SUFFIXES:
        return _MigrationSourceSelection(resolved, "persona_bundle")
    if resolved.name.casefold() != "omnivoice.db":
        raise ValueError(
            "Copied SQLite source type must retain the published name omnivoice.db"
        )
    if not _is_sqlite_file(resolved):
        raise ValueError("Copied omnivoice.db does not have a SQLite header")
    return _MigrationSourceSelection(resolved, "sqlite")


def _reject_live_or_protected_source(source: Path) -> None:
    protected: list[Path] = [repository_root()]
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        local_root = Path(local_app_data).expanduser()
        protected.extend((local_root / "GalaxyAIStudio", local_root / "OmniVoice"))
    app_data = os.environ.get("APPDATA", "").strip()
    if app_data:
        protected.append(Path(app_data).expanduser() / "OmniVoice")
    for variable in ("OMNIVOICE_DATA_DIR", "VOICESTUDIO_RUNTIME_ROOT"):
        override = os.environ.get(variable, "").strip()
        if override:
            protected.append(Path(override).expanduser())
    home = Path.home()
    protected.extend(
        (
            home / ".omnivoice",
            home / "Library" / "Application Support" / "OmniVoice",
        )
    )
    for root in protected:
        if _is_within(source, root):
            raise ValueError(
                f"Migration source is a live or protected repository path: {source.name}"
            )


def _inspect_directory(
    root: Path,
    approved_roots: tuple[Path, ...],
    sandbox: Path,
    inspection: _Inspection,
) -> None:
    files = tuple(_walk_regular_files(root, inspection))
    databases = tuple(path for path in files if _is_sqlite_file(path))
    if not databases:
        inspection.warnings.append("No readable SQLite database was found in the copied source")
    for database in databases:
        _inspect_database(database, root, approved_roots, inspection)
    for bundle in (path for path in files if path.suffix.casefold() in _BUNDLE_SUFFIXES):
        _inspect_bundle(bundle, sandbox, inspection)
    _inspect_discovered_files(root, files, databases, inspection)


def _walk_regular_files(root: Path, inspection: _Inspection) -> list[Path]:
    files: list[Path] = []

    def visit(directory: Path) -> None:
        inspection.check_cancelled()
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: item.name.casefold())
        for entry in entries:
            inspection.check_cancelled()
            path = Path(entry.path)
            info = entry.stat(follow_symlinks=False)
            if _is_link_like(info):
                inspection.unsupported.append(
                    MigrationFinding(path.relative_to(root).as_posix(), "link or reparse point")
                )
            elif stat.S_ISDIR(info.st_mode):
                visit(path)
            elif stat.S_ISREG(info.st_mode):
                files.append(path)

    visit(root)
    return files


def _inspect_database(
    database: Path,
    data_root: Path,
    approved_roots: tuple[Path, ...],
    inspection: _Inspection,
) -> None:
    _reject_sqlite_sidecars(database)
    quoted_path = quote(database.resolve().as_posix(), safe="/:")
    with closing(
        sqlite3.connect(f"file:{quoted_path}?mode=ro", uri=True)
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if not str(row[0]).startswith("sqlite_")
        }
        for table in sorted(tables - set(_KNOWN_COLUMNS) - _UNSUPPORTED_TABLES):
            inspection.check_cancelled()
            inspection.warnings.append(
                f"forward-version: unknown table '{table}' was not mapped"
            )
        for table in sorted(tables & _UNSUPPORTED_TABLES):
            inspection.check_cancelled()
            inspection.unsupported.append(
                MigrationFinding(table, "runtime, credential, or application state is not migrated")
            )
        for table, known_columns in _KNOWN_COLUMNS.items():
            inspection.check_cancelled()
            if table not in tables:
                continue
            actual_columns = _table_columns(connection, table)
            extras = sorted(actual_columns - set(known_columns))
            if extras:
                inspection.warnings.append(
                    f"forward-version: table '{table}' has unknown columns: {', '.join(extras)}"
                )
            selected = tuple(column for column in known_columns if column in actual_columns)
            rows = _select_known_rows(connection, table, selected)
            _map_table(table, rows, data_root, approved_roots, inspection)


def _reject_sqlite_sidecars(database: Path) -> None:
    sidecars = tuple(
        Path(f"{database}{suffix}") for suffix in ("-wal", "-shm", "-journal")
    )
    present = tuple(path.name for path in sidecars if path.exists())
    if present:
        raise ValueError(
            "SQLite WAL/journal sidecars are not supported by read-only rehearsal: "
            + ", ".join(present)
        )


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _select_known_rows(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    if not columns:
        return ()
    selection = ", ".join(f'"{column}"' for column in columns)
    order = ' ORDER BY "id"' if "id" in columns else ""
    return tuple(
        dict(row)
        for row in connection.execute(f'SELECT {selection} FROM "{table}"{order}')
    )


def _map_table(
    table: str,
    rows: tuple[dict[str, Any], ...],
    data_root: Path,
    approved_roots: tuple[Path, ...],
    inspection: _Inspection,
) -> None:
    mapper = {
        "voice_profiles": _map_voice_profile,
        "generation_history": _map_generation_history,
        "dub_history": _map_dub_history,
        "studio_projects": _map_studio_project,
        "export_history": _map_export_history,
        "glossary_terms": _map_glossary_term,
        "pronunciation_entries": _map_pronunciation_entry,
    }[table]
    target = getattr(inspection, table)
    for row in rows:
        inspection.check_cancelled()
        candidate = mapper(row, data_root, approved_roots)
        if table == "export_history" and (
            not candidate.assets
            or any(asset.state == "unsafe" for asset in candidate.assets)
        ):
            source_id = _text(row.get("id"))
            inspection.assets.extend(candidate.assets)
            inspection.warnings.append(
                f"export_history {source_id} is unsafe or has no relinkable output"
            )
            inspection.unsupported.append(
                MigrationFinding(source_id, "unsafe or absent export output")
            )
            continue
        target.append(candidate)
        inspection.assets.extend(candidate.assets)


def _map_voice_profile(
    row: dict[str, Any],
    data_root: Path,
    approved_roots: tuple[Path, ...],
) -> MigrationCandidate:
    warnings: list[str] = []
    assets = _assets_for_fields(
        row,
        (
            ("reference_audio", "ref_audio_path"),
            ("locked_audio", "locked_audio_path"),
            ("consent_recording", "consent_audio_path"),
        ),
        data_root,
        approved_roots,
    )
    consent_asset = next((asset for asset in assets if asset.role == "consent_recording"), None)
    consent_path, _ = _resolve_asset_path(
        row.get("consent_audio_path"), data_root, approved_roots
    )
    recorded_at = _normalize_timestamp(row.get("consent_recorded_at"))
    confirmed = bool(
        _is_strict_true(row.get("verified_own_voice"))
        and _text(row.get("consent_text")).strip()
        and recorded_at
        and consent_asset is not None
        and consent_asset.state in {"managed", "linked"}
        and consent_path is not None
        and _is_valid_audio(consent_path)
    )
    if not confirmed:
        warnings.append("Consent evidence is incomplete; local re-attestation is required")
    consent = ConsentRecord(
        confirmed=confirmed,
        basis="self-recorded-statement" if confirmed else "",
        statement=_text(row.get("consent_text")),
        recorded_at=recorded_at if confirmed else "",
        provenance=consent_asset.hint if consent_asset else "",
    )
    data: dict[str, Any] = {
        "name": _text(row.get("name")) or "Untitled voice",
        "source": _voice_kind(row.get("kind")),
        "language": _text(row.get("language")) or "auto",
        "description": _text(row.get("description")),
        "reference_text": _text(row.get("ref_text")),
        "instruction": _text(row.get("instruct")),
        "personality": _text(row.get("personality")),
        "seed": row.get("seed"),
        "is_locked": _is_strict_true(row.get("is_locked")),
        "is_demo": _is_strict_true(row.get("is_demo")),
        "verified_own_voice_evidence": _is_strict_true(
            row.get("verified_own_voice")
        ),
        "created_at": row.get("created_at"),
    }
    design_state = _bounded_json(row.get("vd_states"), "vd_states", warnings)
    if design_state is not None:
        data["design_state"] = design_state
    return MigrationCandidate(
        source_id=_text(row.get("id")),
        target="voice_profile",
        data=data,
        assets=assets,
        warnings=tuple(warnings),
        consent=consent,
    )


def _map_generation_history(
    row: dict[str, Any], data_root: Path, approved_roots: tuple[Path, ...]
) -> MigrationCandidate:
    assets = _assets_for_fields(
        row, (("generated_audio", "audio_path"),), data_root, approved_roots
    )
    return MigrationCandidate(
        source_id=_text(row.get("id")),
        target="studio_take",
        data={
            "text": _text(row.get("text")),
            "mode": _text(row.get("mode")),
            "language": _text(row.get("language")),
            "instruction": _text(row.get("instruct")),
            "profile_id": _text(row.get("profile_id")),
            "duration_seconds": row.get("duration_seconds"),
            "generation_time": row.get("generation_time"),
            "seed": row.get("seed"),
            "starred": bool(row.get("starred")),
            "created_at": row.get("created_at"),
        },
        assets=assets,
    )


def _map_dub_history(
    row: dict[str, Any], data_root: Path, approved_roots: tuple[Path, ...]
) -> MigrationCandidate:
    warnings: list[str] = []
    assets: list[MigrationAsset] = []
    data: dict[str, Any] = {
        "filename": _text(row.get("filename")),
        "duration": row.get("duration"),
        "segments_count": row.get("segments_count"),
        "language": _text(row.get("language")),
        "language_code": _text(row.get("language_code")),
        "content_hash": _text(row.get("content_hash")),
        "created_at": row.get("created_at"),
    }
    tracks_payload = _bounded_json(row.get("tracks"), "tracks", warnings)
    if tracks_payload is not None:
        tracks, track_assets = _normalize_dub_tracks(
            tracks_payload, data_root, approved_roots, warnings
        )
        if tracks is not None:
            data["tracks"] = tracks
            assets.extend(track_assets)
    job_payload = _bounded_json(row.get("job_data"), "job_data", warnings)
    if job_payload is not None:
        job, job_assets = _normalize_dub_job(
            job_payload, data_root, approved_roots, warnings
        )
        if job is not None:
            data["job"] = job
            assets.extend(job_assets)
    return MigrationCandidate(
        source_id=_text(row.get("id")),
        target="dubbing_project",
        data=data,
        assets=tuple(assets),
        warnings=tuple(warnings),
    )


def _map_studio_project(
    row: dict[str, Any], data_root: Path, approved_roots: tuple[Path, ...]
) -> MigrationCandidate:
    warnings: list[str] = []
    assets = _assets_for_fields(
        row,
        (("source_video", "video_path"), ("source_audio", "audio_path")),
        data_root,
        approved_roots,
    )
    data: dict[str, Any] = {
        "name": _text(row.get("name")) or "Untitled project",
        "duration": row.get("duration"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    state = _bounded_json(row.get("state_json"), "state_json", warnings)
    if state is not None:
        normalized_state, state_assets = _normalize_studio_state(
            state, data_root, approved_roots, warnings
        )
        if normalized_state is not None:
            data["state"] = normalized_state
            assets = (*assets, *state_assets)
    return MigrationCandidate(
        source_id=_text(row.get("id")),
        target="studio_project",
        data=data,
        assets=assets,
        warnings=tuple(warnings),
    )


def _normalize_dub_tracks(
    value: Any,
    data_root: Path,
    approved_roots: tuple[Path, ...],
    warnings: list[str],
) -> tuple[list[str | dict[str, Any]] | None, tuple[MigrationAsset, ...]]:
    if not isinstance(value, list):
        warnings.append("tracks: expected a list; unsupported payload omitted")
        return None, ()
    normalized: list[str | dict[str, Any]] = []
    assets: list[MigrationAsset] = []
    allowed = {"id", "track_id", "language", "language_code", "speaker", "segments"}
    paths = {
        "output_path": "dub_output",
        "audio_path": "dub_output",
        "path": "dub_output",
        "dubbed_path": "dub_output",
    }
    for index, raw_track in enumerate(value):
        if isinstance(raw_track, str):
            if raw_track.strip():
                normalized.append(raw_track)
            else:
                warnings.append(f"tracks[{index}]: empty track identifier omitted")
            continue
        if not isinstance(raw_track, Mapping):
            warnings.append(f"tracks[{index}]: unsupported track value omitted")
            continue
        track: dict[str, Any] = {}
        track_id = raw_track.get("id") or raw_track.get("track_id")
        if track_id is not None:
            track["id"] = _text(track_id)
        for key in ("language", "language_code", "speaker"):
            if raw_track.get(key) is not None:
                track[key] = _text(raw_track[key])
        if "segments" in raw_track:
            track["segments"] = _normalize_segments(
                raw_track.get("segments"), f"tracks[{index}].segments", warnings
            )
        for field, role in paths.items():
            asset = _classify_asset(
                role, raw_track.get(field), data_root, approved_roots
            )
            if asset:
                assets.append(asset)
        extras = sorted(set(raw_track) - allowed - set(paths))
        if extras:
            warnings.append(
                f"tracks[{index}]: unsupported fields omitted: {', '.join(extras)}"
            )
        normalized.append(track)
    return normalized, tuple(assets)


def _normalize_dub_job(
    value: Any,
    data_root: Path,
    approved_roots: tuple[Path, ...],
    warnings: list[str],
) -> tuple[dict[str, Any] | None, tuple[MigrationAsset, ...]]:
    if not isinstance(value, Mapping):
        warnings.append("job_data: expected an object; unsupported payload omitted")
        return None, ()
    normalized: dict[str, Any] = {}
    allowed = {
        "id",
        "job_id",
        "source_language",
        "target_language",
        "language",
        "language_code",
        "status",
        "segments",
    }
    for key in (
        "source_language",
        "target_language",
        "language",
        "language_code",
        "status",
    ):
        if value.get(key) is not None:
            normalized[key] = _text(value[key])
    if "segments" in value:
        normalized["segments"] = _normalize_segments(
            value.get("segments"), "job_data.segments", warnings
        )
    paths = {
        "source_path": "dub_source",
        "video_path": "dub_source",
        "audio_path": "dub_source",
        "output_path": "dub_output",
        "final_output_path": "dub_output",
        "final_audio_path": "dub_output",
        "final_video_path": "dub_output",
        "vocals_path": "dub_stem",
        "instrumental_path": "dub_stem",
    }
    assets = tuple(
        asset
        for field, role in paths.items()
        if (asset := _classify_asset(role, value.get(field), data_root, approved_roots))
        is not None
    )
    extras = sorted(set(value) - allowed - set(paths))
    if extras:
        warnings.append(
            f"job_data: unsupported fields omitted: {', '.join(extras)}"
        )
    return normalized, assets


def _normalize_studio_state(
    value: Any,
    data_root: Path,
    approved_roots: tuple[Path, ...],
    warnings: list[str],
) -> tuple[dict[str, Any] | None, tuple[MigrationAsset, ...]]:
    if not isinstance(value, Mapping):
        warnings.append("state_json: expected an object; unsupported payload omitted")
        return None, ()
    normalized: dict[str, Any] = {}
    scalar_keys = (
        "language",
        "source_language",
        "target_language",
        "version",
        "playhead",
    )
    for key in scalar_keys:
        item = value.get(key)
        if isinstance(item, (str, int, float)) and not isinstance(item, bool):
            normalized[key] = item
    for key in ("timeline", "segments"):
        if key in value:
            normalized[key] = _normalize_segments(
                value.get(key), f"state_json.{key}", warnings
            )
    paths = {
        "output_path": "studio_output",
        "preview_path": "studio_preview",
    }
    assets = tuple(
        asset
        for field, role in paths.items()
        if (asset := _classify_asset(role, value.get(field), data_root, approved_roots))
        is not None
    )
    allowed = set(scalar_keys) | {"timeline", "segments"} | set(paths)
    extras = sorted(set(value) - allowed)
    if extras:
        warnings.append(
            f"state_json: unsupported fields omitted: {', '.join(extras)}"
        )
    return normalized, assets


def _normalize_segments(
    value: Any,
    label: str,
    warnings: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        warnings.append(f"{label}: unsupported non-list segments omitted")
        return []
    allowed = {
        "id",
        "segment_id",
        "start",
        "end",
        "duration",
        "text",
        "translated_text",
        "speaker",
        "language",
        "voice_profile_id",
    }
    normalized: list[dict[str, Any]] = []
    for index, raw_segment in enumerate(value):
        if not isinstance(raw_segment, Mapping):
            warnings.append(f"{label}[{index}]: unsupported segment omitted")
            continue
        segment: dict[str, Any] = {}
        segment_id = raw_segment.get("id") or raw_segment.get("segment_id")
        if segment_id is not None:
            segment["id"] = _text(segment_id)
        for key in ("start", "end", "duration"):
            item = raw_segment.get(key)
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                segment[key] = item
        for key in (
            "text",
            "translated_text",
            "speaker",
            "language",
            "voice_profile_id",
        ):
            if raw_segment.get(key) is not None:
                segment[key] = _text(raw_segment[key])
        extras = sorted(set(raw_segment) - allowed)
        if extras:
            warnings.append(
                f"{label}[{index}]: unsupported fields omitted: {', '.join(extras)}"
            )
        normalized.append(segment)
    return normalized


def _map_export_history(
    row: dict[str, Any], data_root: Path, approved_roots: tuple[Path, ...]
) -> MigrationCandidate:
    assets = _assets_for_fields(
        row, (("exported_output", "destination_path"),), data_root, approved_roots
    )
    return MigrationCandidate(
        source_id=_text(row.get("id")),
        target="export_record",
        data={
            "filename": _text(row.get("filename")),
            "mode": _text(row.get("mode")),
            "created_at": row.get("created_at"),
        },
        assets=assets,
    )


def _map_glossary_term(
    row: dict[str, Any], data_root: Path, approved_roots: tuple[Path, ...]
) -> MigrationCandidate:
    del data_root, approved_roots
    return MigrationCandidate(
        source_id=_text(row.get("id")),
        target="glossary_term",
        data={
            "project_id": _text(row.get("project_id")),
            "source": _text(row.get("source")),
            "target": _text(row.get("target")),
            "note": _text(row.get("note")),
            "automatic": bool(row.get("auto")),
            "created_at": row.get("created_at"),
        },
    )


def _map_pronunciation_entry(
    row: dict[str, Any], data_root: Path, approved_roots: tuple[Path, ...]
) -> MigrationCandidate:
    del data_root, approved_roots
    return MigrationCandidate(
        source_id=_text(row.get("id")),
        target="pronunciation_entry",
        data={
            "term": _text(row.get("term")),
            "replacement": _text(row.get("replacement")),
            "type": _text(row.get("type")),
            "language": _text(row.get("language")),
            "enabled": bool(row.get("enabled")),
            "created_at": row.get("created_at"),
        },
    )


def _assets_for_fields(
    row: Mapping[str, Any],
    fields: tuple[tuple[str, str], ...],
    data_root: Path,
    approved_roots: tuple[Path, ...],
) -> tuple[MigrationAsset, ...]:
    return tuple(
        asset
        for role, column in fields
        if (asset := _classify_asset(role, row.get(column), data_root, approved_roots))
        is not None
    )


def _classify_asset(
    role: str,
    raw_hint: Any,
    data_root: Path,
    approved_roots: tuple[Path, ...],
) -> MigrationAsset | None:
    hint = _text(raw_hint).strip()
    if not hint:
        return None
    resolved, state = _resolve_asset_path(hint, data_root, approved_roots)
    assert resolved is not None
    byte_size = resolved.stat().st_size if state in {"managed", "linked"} else 0
    return MigrationAsset(role=role, hint=hint, state=state, byte_size=byte_size)


def _resolve_asset_path(
    raw_hint: Any,
    data_root: Path,
    approved_roots: tuple[Path, ...],
) -> tuple[Path | None, AssetState]:
    hint = _text(raw_hint).strip()
    if not hint:
        return None, "missing"
    path = Path(hint).expanduser()
    if path.is_absolute():
        resolved = path.resolve(strict=False)
        if not any(_is_within(resolved, root) for root in approved_roots):
            state: AssetState = "unsafe"
        elif resolved.is_file():
            state = "managed" if _is_within(resolved, data_root) else "linked"
        else:
            state = "missing"
    else:
        resolved = (data_root / path).resolve(strict=False)
        if not _is_within(resolved, data_root):
            state = "unsafe"
        elif resolved.is_file():
            state = "managed"
        else:
            state = "missing"
    return resolved, state


def _inspect_bundle(bundle: Path, sandbox: Path, inspection: _Inspection) -> None:
    bundle_sandbox = sandbox / f"bundle-{len(inspection.persona_bundles)}"
    safe_members: dict[str, Path] = {}
    bundle_assets: list[MigrationAsset] = []
    with zipfile.ZipFile(bundle) as archive:
        infos = archive.infolist()
        rejection = _archive_rejection(infos)
        if rejection:
            inspection.warnings.append(f"Bundle rejected ({bundle.name}): {rejection}")
            inspection.unsupported.append(MigrationFinding(bundle.name, rejection))
            inspection.assets.extend(_unsafe_archive_assets(infos))
            return
        bundle_sandbox.mkdir()
        streamed_total = 0
        for info in infos:
            inspection.check_cancelled()
            if info.is_dir():
                continue
            role = _bundle_asset_role(info.filename)
            destination = (bundle_sandbox / PurePosixPath(info.filename)).resolve()
            if not _is_within(destination, bundle_sandbox):
                inspection.warnings.append(f"Bundle rejected ({bundle.name}): path traversal")
                inspection.unsupported.append(
                    MigrationFinding(bundle.name, "archive path traversal")
                )
                return
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                streamed_total += _copy_bounded_member(
                    archive,
                    info,
                    destination,
                    remaining_total=MAX_ARCHIVE_TOTAL_BYTES - streamed_total,
                    check_cancelled=inspection.check_cancelled,
                )
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                inspection.warnings.append(f"Bundle rejected ({bundle.name}): {error}")
                inspection.unsupported.append(MigrationFinding(bundle.name, str(error)))
                return
            safe_members[info.filename] = destination
            if role:
                bundle_assets.append(
                    MigrationAsset(
                        role=role,
                        hint=info.filename,
                        state="managed",
                        byte_size=info.file_size,
                    )
                )

    inspection.assets.extend(bundle_assets)
    manifest_path = safe_members.get("manifest.json") or safe_members.get("metadata.json")
    if manifest_path is None:
        inspection.warnings.append(f"Persona bundle has no readable manifest: {bundle.name}")
        return
    manifest = _load_json_file(manifest_path, "persona manifest", inspection.warnings)
    if not isinstance(manifest, dict):
        return
    declared_assets = _declared_bundle_assets(manifest)
    for role, member, checksum in declared_assets:
        if member not in safe_members and not any(asset.hint == member for asset in bundle_assets):
            declared_state: AssetState = (
                "unsafe" if _unsafe_declared_member(member) else "missing"
            )
            missing = MigrationAsset(
                role=role,
                hint=member,
                state=declared_state,
                expected_sha256=checksum,
            )
            bundle_assets.append(missing)
            inspection.assets.append(missing)

    legacy = bundle.suffix.casefold() == ".omnivoice"
    warnings: list[str] = []
    consent = _bundle_consent(safe_members, manifest, legacy, warnings)
    persona = manifest.get("persona") if isinstance(manifest.get("persona"), dict) else manifest
    data = _persona_data(persona, manifest, legacy, warnings)
    data["verified_own_voice_evidence"] = consent.confirmed
    inspection.persona_bundles.append(
        MigrationCandidate(
            source_id=_text(persona.get("id") or persona.get("profile_id") or bundle.stem),
            target="persona_bundle",
            data=data,
            assets=tuple(bundle_assets),
            warnings=tuple(warnings),
            consent=consent,
        )
    )


def _archive_rejection(infos: list[zipfile.ZipInfo]) -> str:
    members = infos
    try:
        validate_archive_members(members, policy=_archive_policy())
    except ValueError as error:
        return str(error)
    seen_controls: set[str] = set()
    for info in members:
        control = _archive_control_key(info.filename)
        if control and control in seen_controls:
            return f"duplicate archive control member: {control}"
        if control:
            seen_controls.add(control)
        unsafe = _unsafe_archive_member(info)
        if unsafe:
            return f"{info.filename}: {unsafe}"
    return ""


def _archive_control_key(name: str) -> str:
    basename = PurePosixPath(name).name.casefold()
    if basename in {"manifest.json", "metadata.json", "consent.json"}:
        return basename
    for prefix in ("ref_audio", "locked_audio", "consent_audio", "preview"):
        if basename.startswith(prefix):
            return prefix
    return ""


def _unsafe_archive_assets(infos: list[zipfile.ZipInfo]) -> tuple[MigrationAsset, ...]:
    return tuple(
        MigrationAsset(role=role, hint=info.filename, state="unsafe")
        for info in infos
        if not info.is_dir() and (role := _bundle_asset_role(info.filename))
    )


def _unsafe_archive_member(info: zipfile.ZipInfo) -> str:
    try:
        validate_archive_members([info], policy=_archive_policy())
    except ValueError as error:
        return str(error)
    return ""


def _copy_bounded_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    *,
    remaining_total: int,
    check_cancelled: Callable[[], None] | None = None,
) -> int:
    return copy_archive_member(
        archive,
        info,
        destination,
        policy=_archive_policy(),
        remaining_total=remaining_total,
        check_cancelled=check_cancelled,
    )


def _archive_policy() -> ArchivePolicy:
    return ArchivePolicy(
        max_members=MAX_ARCHIVE_MEMBERS,
        max_member_bytes=MAX_ARCHIVE_MEMBER_BYTES,
        max_total_bytes=MAX_ARCHIVE_TOTAL_BYTES,
        max_compression_ratio=MAX_COMPRESSION_RATIO,
    )


def _bundle_asset_role(name: str) -> str:
    lowered = PurePosixPath(name).name.casefold()
    if lowered.startswith("consent_audio"):
        return "consent_recording"
    if lowered.startswith("locked_audio"):
        return "locked_audio"
    if lowered.startswith("ref_audio"):
        return "reference_audio"
    if lowered == "preview.wav" or PurePosixPath(name).suffix.casefold() in _MEDIA_SUFFIXES:
        return "preview"
    return ""


def _declared_bundle_assets(
    manifest: Mapping[str, Any],
) -> tuple[tuple[str, str, str], ...]:
    declared: list[tuple[str, str, str]] = []
    members = manifest.get("members")
    if isinstance(members, Mapping):
        member_roles = {
            "ref_audio": "reference_audio",
            "locked_audio": "locked_audio",
            "consent_audio": "consent_recording",
            "preview": "preview",
        }
        for key, role in member_roles.items():
            value = members.get(key)
            if isinstance(value, str) and value.strip():
                declared.append((role, value, ""))
    assets = manifest.get("assets")
    if isinstance(assets, Mapping):
        for role, value in assets.items():
            if isinstance(value, str) and value.strip():
                declared.append((_text(role), value, ""))
            elif isinstance(value, Mapping):
                member = _text(
                    value.get("path") or value.get("member") or value.get("name")
                ).strip()
                if member:
                    declared.append(
                        (
                            _text(role),
                            member,
                            _text(value.get("sha256") or value.get("checksum")),
                        )
                    )
    aliases = (
        ("reference_audio", "ref_audio_file"),
        ("locked_audio", "locked_audio_file"),
        ("preview", "preview_file"),
        ("consent_recording", "consent_audio_file"),
    )
    for role, key in aliases:
        value = manifest.get(key)
        if isinstance(value, str) and value.strip():
            declared.append((role, value, ""))
    return tuple(declared)


def _unsafe_declared_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(
        path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or (path.parts and path.parts[0].endswith(":"))
    )


def _bundle_consent(
    safe_members: Mapping[str, Path],
    manifest: Mapping[str, Any],
    legacy: bool,
    warnings: list[str],
) -> ConsentRecord:
    if legacy:
        warnings.append("Legacy persona consent is unverified; local re-attestation is required")
        return ConsentRecord()
    consent_path = safe_members.get("consent.json")
    members = manifest.get("members")
    declared_consent = members.get("consent_audio") if isinstance(members, Mapping) else None
    consent_audio = (
        declared_consent
        if isinstance(declared_consent, str) and declared_consent in safe_members
        else ""
    )
    if consent_path is None:
        warnings.append("Persona consent attestation is missing; local re-attestation is required")
        return ConsentRecord(provenance=consent_audio)
    warnings_sink: list[str] = []
    payload = _load_json_file(consent_path, "consent attestation", warnings_sink)
    warnings.extend(warnings_sink)
    data = payload if isinstance(payload, dict) else {}
    statement = _text(data.get("consent_text"))
    method = _text(data.get("method"))
    normalized_timestamp = _normalize_timestamp(data.get("recorded_at"))
    consent_audio_path = safe_members.get(consent_audio) if consent_audio else None
    confirmed = bool(
        _is_strict_true(data.get("verified_own_voice"))
        and _is_strict_true(data.get("has_recording"))
        and method == "self-recorded-statement"
        and statement.strip()
        and normalized_timestamp
        and consent_audio_path is not None
        and _is_valid_audio(consent_audio_path)
    )
    if not confirmed:
        warnings.append("Persona consent evidence is incomplete; local re-attestation is required")
    return ConsentRecord(
        confirmed=confirmed,
        basis=method if confirmed else "",
        statement=statement,
        recorded_at=normalized_timestamp if confirmed else "",
        provenance=consent_audio,
    )


def _persona_data(
    persona: Mapping[str, Any],
    manifest: Mapping[str, Any],
    legacy: bool,
    warnings: list[str],
) -> dict[str, Any]:
    kind = persona.get("kind") or persona.get("voice_kind")
    tags = manifest.get("tags") if isinstance(manifest.get("tags"), list) else []
    license_data = manifest.get("license") if isinstance(manifest.get("license"), dict) else {}
    engine = manifest.get("engine") if isinstance(manifest.get("engine"), dict) else {}
    data: dict[str, Any] = {
        "name": _text(persona.get("name") or persona.get("profile_name") or "Untitled voice"),
        "source": _voice_kind(kind),
        "language": _text(persona.get("language") or "auto"),
        "description": _text(persona.get("description")),
        "personality": _text(persona.get("personality")),
        "reference_text": _text(persona.get("reference_text") or persona.get("ref_text")),
        "instruction": _text(persona.get("instruction") or persona.get("instruct")),
        "seed": persona.get("seed") if type(persona.get("seed")) is int else None,
        "is_locked": _is_strict_true(persona.get("is_locked")),
        "engine_id": _text(engine.get("id")),
        "design_params": _normalize_design_params(engine.get("design_params")),
        "tags": [_text(tag) for tag in tags if _text(tag).strip()],
        "license_spdx": _text(license_data.get("spdx") or manifest.get("license_spdx")),
        "license_custom_text": _text(license_data.get("custom_text")),
        "preview": _normalize_preview(manifest.get("preview")),
        "legacy": legacy,
    }
    design_state = _bounded_json(persona.get("vd_states"), "persona.vd_states", warnings)
    if design_state is not None:
        data["design_state"] = design_state
    return data


def _normalize_design_params(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    allowed = ("gender", "age", "pitch", "style", "accent", "dialect")
    return {
        key: value[key]
        for key in allowed
        if isinstance(value.get(key), (str, int, float))
        and not isinstance(value.get(key), bool)
    }


def _normalize_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    preview: dict[str, Any] = {}
    filename = value.get("file")
    if isinstance(filename, str) and not _unsafe_declared_member(filename):
        preview["file"] = filename
    if isinstance(value.get("watermarked"), bool):
        preview["watermarked"] = value["watermarked"]
    duration = value.get("duration_s")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
        preview["duration_s"] = duration
    sample_rate = value.get("sample_rate")
    if type(sample_rate) is int and sample_rate > 0:
        preview["sample_rate"] = sample_rate
    return preview


def _inspect_discovered_files(
    root: Path,
    files: tuple[Path, ...],
    databases: tuple[Path, ...],
    inspection: _Inspection,
) -> None:
    referenced = {
        (root / asset.hint).resolve(strict=False)
        for asset in inspection.assets
        if asset.state == "managed" and not Path(asset.hint).is_absolute()
    }
    ignored = set(databases)
    for path in files:
        if (
            path in ignored
            or path.suffix.casefold() in _BUNDLE_SUFFIXES
            or path.resolve() in referenced
        ):
            continue
        relative = path.relative_to(root).as_posix()
        lowered_parts = {part.casefold() for part in path.relative_to(root).parts}
        if path.suffix.casefold() == ".log" or lowered_parts & {
            "cache",
            "caches",
            "engines",
            "logs",
            "model_cache",
            "models",
            "previews",
            "runtime",
            "temp",
        }:
            inspection.unsupported.append(
                MigrationFinding(relative, "log, model cache, engine, or temporary state")
            )
            continue
        if path.suffix.casefold() == ".json":
            payload = _load_json_file(path, relative, inspection.warnings)
            if _is_unsupported_json(relative, payload):
                inspection.unsupported.append(
                    MigrationFinding(relative, "settings, credentials, or sensitive JSON")
                )
                continue
            document = _normalize_document(payload, relative, inspection.warnings)
            if document:
                target, data = document
                inspection.discovered_documents.append(
                    MigrationCandidate(
                        source_id=relative,
                        target=target,
                        data={"relative_path": relative, **data},
                    )
                )
            else:
                inspection.unsupported.append(
                    MigrationFinding(relative, "unknown JSON document signature")
                )
            continue
        suffix = path.suffix.casefold()
        if suffix == ".srt":
            cue_count = _srt_cue_count(path)
            if cue_count <= 0:
                inspection.unsupported.append(
                    MigrationFinding(relative, "invalid or empty SRT timing structure")
                )
                continue
            inspection.discovered_documents.append(
                MigrationCandidate(
                    source_id=relative,
                    target="transcript_document",
                    data={"relative_path": relative, "cue_count": cue_count},
                )
            )
        elif suffix == ".pdf":
            if not _is_valid_pdf(path):
                inspection.unsupported.append(
                    MigrationFinding(relative, "invalid PDF signature")
                )
                continue
            inspection.discovered_documents.append(
                MigrationCandidate(
                    source_id=relative,
                    target="longform_document",
                    data={"relative_path": relative, "format": "pdf"},
                )
            )
        elif suffix == ".epub":
            if not _is_valid_epub(path):
                inspection.unsupported.append(
                    MigrationFinding(relative, "invalid EPUB structure")
                )
                continue
            inspection.discovered_documents.append(
                MigrationCandidate(
                    source_id=relative,
                    target="longform_document",
                    data={"relative_path": relative, "format": "epub"},
                )
            )
        elif suffix in _MEDIA_SUFFIXES:
            if not _is_valid_media(path):
                inspection.unsupported.append(
                    MigrationFinding(relative, "invalid media signature")
                )
                continue
            asset = MigrationAsset(
                role="generated_media",
                hint=relative,
                state="managed",
                byte_size=path.stat().st_size,
            )
            inspection.assets.append(asset)
            inspection.discovered_documents.append(
                MigrationCandidate(
                    source_id=relative,
                    target="generated_asset",
                    data={"relative_path": relative},
                    assets=(asset,),
                )
            )
        else:
            inspection.unsupported.append(MigrationFinding(relative, "unknown source file"))


def _is_unsupported_json(relative: str, payload: Any) -> bool:
    name = PurePosixPath(relative).name.casefold()
    if name in {
        "config.json",
        "credentials.json",
        "secrets.json",
        "settings.json",
        "tokens.json",
    }:
        return True
    return _contains_sensitive_key(payload)


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if re.search(
                r"(?:api[_-]?key|token|secret|password|authorization|credential|cookie)",
                _text(key),
                re.IGNORECASE,
            ):
                return True
            if _contains_sensitive_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _normalize_document(
    payload: Any,
    label: str,
    warnings: list[str],
) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(payload, Mapping):
        return None
    segments = payload.get("segments") or payload.get("cues")
    if isinstance(segments, list) and segments:
        normalized = _normalize_timed_document_segments(segments)
        if normalized is not None:
            return "transcript_document", {"segments": normalized}
        warnings.append(f"{label}: invalid transcript timing structure")
        return None
    chapters = payload.get("chapters")
    if isinstance(chapters, list) and chapters:
        normalized_chapters: list[dict[str, str]] = []
        for chapter in chapters:
            if not isinstance(chapter, Mapping):
                return None
            title = _text(chapter.get("title")).strip()
            text = _text(chapter.get("text") or chapter.get("content")).strip()
            if not title or not text:
                return None
            normalized_chapters.append({"title": title, "text": text})
        return "longform_document", {"chapters": normalized_chapters}
    items = payload.get("items")
    if isinstance(items, list) and items:
        normalized_items: list[dict[str, str]] = []
        for index, item in enumerate(items):
            if isinstance(item, str) and item.strip():
                normalized_items.append({"id": str(index + 1), "text": item.strip()})
            elif isinstance(item, Mapping):
                text = _text(item.get("text")).strip()
                if not text:
                    return None
                normalized_items.append(
                    {"id": _text(item.get("id") or index + 1), "text": text}
                )
            else:
                return None
        return "batch_manifest", {"items": normalized_items}
    return None


def _normalize_timed_document_segments(
    segments: list[Any],
) -> list[dict[str, Any]] | None:
    normalized: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping):
            return None
        start = segment.get("start")
        end = segment.get("end")
        text = _text(segment.get("text")).strip()
        if (
            not isinstance(start, (int, float))
            or isinstance(start, bool)
            or not isinstance(end, (int, float))
            or isinstance(end, bool)
            or start < 0
            or end < start
            or not text
        ):
            return None
        item: dict[str, Any] = {
            "id": _text(segment.get("id") or index + 1),
            "start": start,
            "end": end,
            "text": text,
        }
        if segment.get("speaker") is not None:
            item["speaker"] = _text(segment["speaker"])
        normalized.append(item)
    return normalized


_SRT_TIMING = re.compile(
    r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}$"
)


def _srt_cue_count(path: Path) -> int:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return 0
    return sum(1 for line in lines if _SRT_TIMING.fullmatch(line.strip()))


def _is_valid_pdf(path: Path) -> bool:
    try:
        if path.stat().st_size < 12:
            return False
        with path.open("rb") as source:
            header = source.read(8)
            source.seek(max(0, path.stat().st_size - 1024))
            tail = source.read(1024)
        return header.startswith(b"%PDF-") and b"%%EOF" in tail
    except OSError:
        return False


def _is_valid_epub(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "mimetype" not in names or "META-INF/container.xml" not in names:
                return False
            return archive.read("mimetype") == b"application/epub+zip"
    except (OSError, KeyError, zipfile.BadZipFile):
        return False


def _is_valid_media(path: Path) -> bool:
    if path.suffix.casefold() in {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}:
        return _is_valid_audio(path)
    try:
        with path.open("rb") as source:
            header = source.read(16)
    except OSError:
        return False
    suffix = path.suffix.casefold()
    if suffix in {".mp4", ".mov"}:
        return len(header) >= 12 and header[4:8] == b"ftyp"
    if suffix in {".mkv", ".webm"}:
        return header.startswith(b"\x1aE\xdf\xa3")
    return False


def _load_json_file(path: Path, label: str, warnings: list[str]) -> Any | None:
    try:
        size = path.stat().st_size
    except OSError as error:
        warnings.append(f"{label}: cannot read JSON: {error}")
        return None
    if size > MAX_JSON_BYTES:
        warnings.append(f"{label}: JSON size limit exceeded")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        warnings.append(f"{label}: invalid JSON: {error}")
        return None


def _bounded_json(raw: Any, label: str, warnings: list[str]) -> Any | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        warnings.append(f"{label}: expected JSON text")
        return None
    if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        warnings.append(f"{label}: JSON size limit exceeded")
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        warnings.append(f"{label}: invalid JSON: {error.msg}")
        return None


def _validate_normalized_candidates(sandbox: Path, inspection: _Inspection) -> None:
    groups = (
        inspection.voice_profiles,
        inspection.persona_bundles,
        inspection.generation_history,
        inspection.dub_history,
        inspection.studio_projects,
        inspection.export_history,
        inspection.glossary_terms,
        inspection.pronunciation_entries,
        inspection.discovered_documents,
    )
    payload = [
        {
            "source_id": candidate.source_id,
            "target": candidate.target,
            "data": dict(candidate.data),
            "consent": asdict(candidate.consent),
        }
        for group in groups
        for candidate in group
    ]
    normalized = sandbox / "normalized-candidates.json"
    normalized.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    decoded = json.loads(normalized.read_text(encoding="utf-8"))
    if not isinstance(decoded, list):
        raise ValueError("Normalized migration candidates did not round-trip")
    for candidate in (*inspection.voice_profiles, *inspection.persona_bundles):
        data = candidate.data
        VoiceProfileRecord.from_payload(
            {
                "voice_id": candidate.source_id,
                "revision": 1,
                "name": data.get("name"),
                "source": data.get("source"),
                "language": data.get("language"),
                "engine_id": "omnivoice",
                "selection": {
                    "source": "reference",
                    "reference_text": data.get("reference_text"),
                    "instruction": data.get("instruction"),
                },
                "notes": data.get("description"),
                "consent": asdict(candidate.consent),
            }
        )


def _is_sqlite_file(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open("rb") as source:
            return source.read(16) == b"SQLite format 3\0"
    except OSError:
        return False


def _voice_kind(value: Any) -> str:
    kind = _text(value).strip().casefold()
    if kind == "clone":
        return "cloned"
    if kind in {"design", "designed", "voice_design", "voice-design"}:
        return "designed"
    return "imported"


def _is_strict_true(value: Any) -> bool:
    return value is True or (type(value) is int and value == 1)


def _normalize_timestamp(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    parsed: datetime
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            return ""
        try:
            parsed = datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return ""
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return ""
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
    else:
        return ""
    return parsed.isoformat()


def _is_valid_audio(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 1000:
            return False
        suffix = path.suffix.casefold()
        if suffix == ".wav":
            with wave.open(str(path), "rb") as audio:
                return bool(
                    audio.getnchannels() > 0
                    and audio.getsampwidth() > 0
                    and audio.getframerate() > 0
                    and audio.getnframes() > 0
                )
        if suffix in {".flac", ".ogg", ".opus", ".mp3", ".m4a", ".mp4"}:
            return _has_valid_audio_stream(path)
    except (OSError, RuntimeError, ValueError, EOFError, wave.Error):
        return False
    return False


def _has_valid_audio_stream(path: Path) -> bool:
    ffprobe = find_ffprobe()
    if not ffprobe:
        return False
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type,codec_name,sample_rate,channels,duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if completed.returncode != 0:
        return False
    try:
        payload = json.loads(completed.stdout or "{}")
        streams = payload.get("streams")
        if not isinstance(streams, list) or not streams:
            return False
        stream = streams[0]
        if not isinstance(stream, Mapping) or stream.get("codec_type") != "audio":
            return False
        duration = stream.get("duration") or (payload.get("format") or {}).get("duration")
        return bool(
            _text(stream.get("codec_name")).strip()
            and int(stream.get("sample_rate") or 0) > 0
            and int(stream.get("channels") or 0) > 0
            and math.isfinite(float(duration))
            and float(duration) > 0
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _is_within(path: Path, root: Path) -> bool:
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    return resolved_path == resolved_root or resolved_path.is_relative_to(resolved_root)


def _is_link_like(file_info: os.stat_result) -> bool:
    attributes = getattr(file_info, "st_file_attributes", 0)
    return stat.S_ISLNK(file_info.st_mode) or bool(
        _REPARSE_POINT_ATTRIBUTE and attributes & _REPARSE_POINT_ATTRIBUTE
    )
