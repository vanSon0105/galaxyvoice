"""Read-only VoiceStudio migration rehearsal over copied local data."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import quote

from ..voice_library.models import ConsentRecord, VoiceProfileRecord
from .models import SourceFingerprint
from .security import fingerprint_source, resolve_approved_path


MAX_JSON_BYTES = 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 512
MAX_COMPRESSION_RATIO = 200

AssetState = Literal["managed", "linked", "missing", "unsafe"]

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


@dataclass(frozen=True)
class MigrationCandidate:
    source_id: str
    target: str
    data: Mapping[str, Any] = field(default_factory=dict)
    assets: tuple[MigrationAsset, ...] = ()
    warnings: tuple[str, ...] = ()
    consent: ConsentRecord = field(default_factory=ConsentRecord)

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
        object.__setattr__(self, "assets", tuple(self.assets))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class MigrationFinding:
    source: str
    reason: str


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


class SourceChangedError(RuntimeError):
    """Raised when source bytes change during a read-only rehearsal."""


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


def inspect_migration_source(
    source: Path,
    *,
    approved_roots: Sequence[Path],
    sandbox_root: Path | None = None,
) -> MigrationDryRun:
    """Inspect a copied database, data directory, or persona bundle without writes."""

    resolved_source = resolve_approved_path(Path(source), approved_roots)
    before = fingerprint_source(resolved_source)
    approved = tuple(Path(root).expanduser().resolve(strict=False) for root in approved_roots)
    inspection = _Inspection()

    sandbox_parent = None
    if sandbox_root is not None:
        sandbox_parent = Path(sandbox_root).expanduser().resolve(strict=False)
        if resolved_source.is_dir() and _is_within(sandbox_parent, resolved_source):
            raise ValueError("Sandbox root cannot be inside the inspected source directory")
        sandbox_parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(dir=sandbox_parent) as temporary:
        sandbox = Path(temporary)
        if resolved_source.is_dir():
            _inspect_directory(resolved_source, approved, sandbox, inspection)
        elif resolved_source.suffix.casefold() in _BUNDLE_SUFFIXES:
            _inspect_bundle(resolved_source, sandbox, inspection)
        elif _is_sqlite_file(resolved_source):
            _inspect_database(resolved_source, resolved_source.parent, approved, inspection)
        else:
            raise ValueError(f"Unsupported migration source: {resolved_source.name}")
        _validate_normalized_candidates(sandbox, inspection)

    after = fingerprint_source(resolved_source)
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
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: item.name.casefold())
        for entry in entries:
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
    quoted_path = quote(database.resolve().as_posix(), safe="/:")
    with sqlite3.connect(f"file:{quoted_path}?mode=ro", uri=True) as connection:
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
            inspection.warnings.append(
                f"forward-version: unknown table '{table}' was not mapped"
            )
        for table in sorted(tables & _UNSUPPORTED_TABLES):
            inspection.unsupported.append(
                MigrationFinding(table, "runtime, credential, or application state is not migrated")
            )
        for table, known_columns in _KNOWN_COLUMNS.items():
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
        candidate = mapper(row, data_root, approved_roots)
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
    confirmed = bool(
        row.get("verified_own_voice")
        and _text(row.get("consent_text")).strip()
        and row.get("consent_recorded_at") is not None
        and consent_asset is not None
        and consent_asset.state in {"managed", "linked"}
    )
    if not confirmed:
        warnings.append("Consent evidence is incomplete; local re-attestation is required")
    consent = ConsentRecord(
        confirmed=confirmed,
        basis="voicestudio-attestation" if confirmed else "",
        statement=_text(row.get("consent_text")),
        recorded_at=_text(row.get("consent_recorded_at")) if confirmed else "",
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
        "is_locked": bool(row.get("is_locked")),
        "is_demo": bool(row.get("is_demo")),
        "verified_own_voice_evidence": bool(row.get("verified_own_voice")),
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
    del data_root, approved_roots
    warnings: list[str] = []
    data: dict[str, Any] = {
        "filename": _text(row.get("filename")),
        "duration": row.get("duration"),
        "segments_count": row.get("segments_count"),
        "language": _text(row.get("language")),
        "language_code": _text(row.get("language_code")),
        "content_hash": _text(row.get("content_hash")),
        "created_at": row.get("created_at"),
    }
    for column in ("tracks", "job_data"):
        parsed = _bounded_json(row.get(column), column, warnings)
        if parsed is not None:
            data[column] = parsed
    return MigrationCandidate(
        source_id=_text(row.get("id")),
        target="dubbing_project",
        data=data,
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
        data["state"] = state
    return MigrationCandidate(
        source_id=_text(row.get("id")),
        target="studio_project",
        data=data,
        assets=assets,
        warnings=tuple(warnings),
    )


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
    byte_size = resolved.stat().st_size if state in {"managed", "linked"} else 0
    return MigrationAsset(role=role, hint=hint, state=state, byte_size=byte_size)


def _inspect_bundle(bundle: Path, sandbox: Path, inspection: _Inspection) -> None:
    bundle_sandbox = sandbox / f"bundle-{len(inspection.persona_bundles)}"
    bundle_sandbox.mkdir()
    safe_members: dict[str, Path] = {}
    bundle_assets: list[MigrationAsset] = []
    with zipfile.ZipFile(bundle) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            inspection.warnings.append(
                f"Archive member count exceeds size limit: {bundle.name}"
            )
        total = 0
        for info in infos[:MAX_ARCHIVE_MEMBERS]:
            if info.is_dir():
                continue
            role = _bundle_asset_role(info.filename)
            unsafe_reason = _unsafe_archive_member(info)
            total += max(0, info.file_size)
            if total > MAX_ARCHIVE_TOTAL_BYTES:
                unsafe_reason = "archive total size limit exceeded"
            if unsafe_reason:
                inspection.warnings.append(f"{bundle.name}:{info.filename}: {unsafe_reason}")
                if role:
                    bundle_assets.append(
                        MigrationAsset(role=role, hint=info.filename, state="unsafe")
                    )
                continue
            destination = (bundle_sandbox / PurePosixPath(info.filename)).resolve()
            if not _is_within(destination, bundle_sandbox):
                inspection.warnings.append(
                    f"{bundle.name}:{info.filename}: archive path traversal"
                )
                if role:
                    bundle_assets.append(
                        MigrationAsset(role=role, hint=info.filename, state="unsafe")
                    )
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_bounded_member(archive, info, destination)
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
    consent = _bundle_consent(safe_members, legacy, warnings)
    persona = manifest.get("persona") if isinstance(manifest.get("persona"), dict) else manifest
    data = _persona_data(persona, manifest, legacy)
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


def _unsafe_archive_member(info: zipfile.ZipInfo) -> str:
    name = info.filename
    path = PurePosixPath(name)
    mode = info.external_attr >> 16
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        return "archive path traversal"
    if path.parts and path.parts[0].endswith(":"):
        return "archive absolute path"
    if stat.S_ISLNK(mode):
        return "archive symbolic link"
    if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
        return "archive member size limit exceeded"
    if info.file_size and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
        return "archive compression ratio limit exceeded"
    return ""


def _copy_bounded_member(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: Path
) -> None:
    written = 0
    with archive.open(info) as source, destination.open("wb") as output:
        while chunk := source.read(64 * 1024):
            written += len(chunk)
            if written > MAX_ARCHIVE_MEMBER_BYTES:
                raise ValueError(f"Archive member exceeded size limit: {info.filename}")
            output.write(chunk)


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
    safe_members: Mapping[str, Path], legacy: bool, warnings: list[str]
) -> ConsentRecord:
    if legacy:
        warnings.append("Legacy persona consent is unverified; local re-attestation is required")
        return ConsentRecord()
    consent_path = safe_members.get("consent.json")
    consent_audio = next(
        (name for name in safe_members if PurePosixPath(name).name.startswith("consent_audio.")),
        "",
    )
    if consent_path is None:
        warnings.append("Persona consent attestation is missing; local re-attestation is required")
        return ConsentRecord(provenance=consent_audio)
    warnings_sink: list[str] = []
    payload = _load_json_file(consent_path, "consent attestation", warnings_sink)
    warnings.extend(warnings_sink)
    data = payload if isinstance(payload, dict) else {}
    statement = _text(data.get("statement") or data.get("consent_text"))
    recorded_at = _text(data.get("recorded_at") or data.get("timestamp"))
    method = _text(data.get("method"))
    confirmed = bool(
        data.get("verified")
        and statement.strip()
        and recorded_at.strip()
        and method.strip()
        and consent_audio
    )
    if not confirmed:
        warnings.append("Persona consent evidence is incomplete; local re-attestation is required")
    return ConsentRecord(
        confirmed=confirmed,
        basis=method if confirmed else "",
        statement=statement,
        recorded_at=recorded_at if confirmed else "",
        provenance=consent_audio,
    )


def _persona_data(
    persona: Mapping[str, Any], manifest: Mapping[str, Any], legacy: bool
) -> dict[str, Any]:
    kind = persona.get("kind") or persona.get("voice_kind")
    tags = persona.get("tags") if isinstance(persona.get("tags"), list) else []
    license_data = manifest.get("license") if isinstance(manifest.get("license"), dict) else {}
    return {
        "name": _text(persona.get("name") or persona.get("profile_name") or "Untitled voice"),
        "source": _voice_kind(kind),
        "language": _text(persona.get("language") or "auto"),
        "description": _text(persona.get("description")),
        "reference_text": _text(persona.get("reference_text") or persona.get("ref_text")),
        "instruction": _text(persona.get("instruction") or persona.get("instruct")),
        "tags": [_text(tag) for tag in tags if _text(tag).strip()],
        "license_spdx": _text(license_data.get("spdx") or manifest.get("license_spdx")),
        "legacy": legacy,
    }


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
            target = _document_target(payload)
            if target:
                inspection.discovered_documents.append(
                    MigrationCandidate(
                        source_id=relative,
                        target=target,
                        data={"relative_path": relative, "payload": payload},
                    )
                )
            else:
                inspection.unsupported.append(
                    MigrationFinding(relative, "unknown JSON document signature")
                )
            continue
        if path.suffix.casefold() in {".epub", ".pdf", ".srt"}:
            target = (
                "transcript_document"
                if path.suffix.casefold() == ".srt"
                else "longform_document"
            )
            inspection.discovered_documents.append(
                MigrationCandidate(
                    source_id=relative,
                    target=target,
                    data={"relative_path": relative},
                )
            )
        elif path.suffix.casefold() in _MEDIA_SUFFIXES:
            inspection.discovered_documents.append(
                MigrationCandidate(
                    source_id=relative,
                    target="generated_asset",
                    data={"relative_path": relative},
                )
            )
        else:
            inspection.unsupported.append(MigrationFinding(relative, "unknown source file"))


def _document_target(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    if isinstance(payload.get("segments"), list) or isinstance(payload.get("cues"), list):
        return "transcript_document"
    if isinstance(payload.get("chapters"), list) or isinstance(payload.get("cast"), list):
        return "longform_document"
    if isinstance(payload.get("items"), list):
        return "batch_manifest"
    return ""


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
