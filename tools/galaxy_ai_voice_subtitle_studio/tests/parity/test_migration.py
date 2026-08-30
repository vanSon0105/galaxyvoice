from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.parity import fingerprint_source
from app.parity.migration import MAX_ARCHIVE_MEMBER_BYTES, MAX_JSON_BYTES, inspect_migration_source


SUPPORTED_SCHEMA = """
CREATE TABLE voice_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ref_audio_path TEXT,
    ref_text TEXT DEFAULT '',
    instruct TEXT DEFAULT '',
    language TEXT DEFAULT 'Auto',
    locked_audio_path TEXT DEFAULT '',
    seed INTEGER,
    is_locked INTEGER DEFAULT 0,
    personality TEXT DEFAULT '',
    description TEXT DEFAULT '',
    is_demo INTEGER DEFAULT 0,
    verified_own_voice INTEGER DEFAULT 0,
    consent_text TEXT DEFAULT '',
    consent_audio_path TEXT DEFAULT '',
    consent_recorded_at REAL,
    kind TEXT DEFAULT 'clone',
    vd_states TEXT,
    created_at REAL,
    future_profile_field TEXT
);
CREATE TABLE generation_history (
    id TEXT PRIMARY KEY, text TEXT, mode TEXT, language TEXT, instruct TEXT,
    profile_id TEXT, audio_path TEXT, duration_seconds REAL,
    generation_time REAL, seed INTEGER, starred INTEGER, created_at REAL
);
CREATE TABLE dub_history (
    id TEXT PRIMARY KEY, filename TEXT, duration REAL, segments_count INTEGER,
    language TEXT, language_code TEXT, tracks TEXT, job_data TEXT,
    content_hash TEXT, created_at REAL
);
CREATE TABLE studio_projects (
    id TEXT PRIMARY KEY, name TEXT, video_path TEXT, audio_path TEXT,
    duration REAL, state_json TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE export_history (
    id TEXT PRIMARY KEY, filename TEXT, destination_path TEXT,
    mode TEXT, created_at REAL
);
CREATE TABLE glossary_terms (
    id TEXT PRIMARY KEY, project_id TEXT, source TEXT, target TEXT,
    note TEXT, auto INTEGER, created_at REAL
);
CREATE TABLE pronunciation_entries (
    id TEXT PRIMARY KEY, term TEXT, replacement TEXT, type TEXT,
    language TEXT, enabled INTEGER, created_at REAL
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT);
CREATE TABLE job_events (id INTEGER PRIMARY KEY, payload TEXT);
CREATE TABLE future_table (id TEXT PRIMARY KEY, payload TEXT);
"""


def build_source_db(
    tmp_path: Path,
    *,
    consent_text: str = "I attest this is my voice",
    consent_recording: str = "consent.wav",
    tracks: str = '[{"speaker": "narrator"}]',
    job_data: str = '{"segments": [{"text": "Hello"}]}',
) -> Path:
    copied_root = tmp_path / "voicestudio-copy"
    copied_root.mkdir()
    for name in ("reference.wav", "locked.wav", "consent.wav", "take.wav"):
        (copied_root / name).write_bytes(name.encode("ascii"))
    linked_audio = tmp_path / "linked.wav"
    linked_audio.write_bytes(b"linked")

    source = copied_root / "omnivoice.db"
    with sqlite3.connect(source) as connection:
        connection.executescript(SUPPORTED_SCHEMA)
        connection.execute(
            """INSERT INTO voice_profiles VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                "voice-1",
                "Primary voice",
                "reference.wav",
                "Reference text",
                "Warm delivery",
                "en",
                "locked.wav",
                42,
                1,
                "calm",
                "fixture voice",
                0,
                1,
                consent_text,
                consent_recording,
                1_700_000_000.0,
                "clone",
                '{"pitch": "medium"}',
                1_699_999_999.0,
                "future-value",
            ),
        )
        connection.execute(
            "INSERT INTO generation_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "take-1",
                "Hello world",
                "clone",
                "en",
                "Warm",
                "voice-1",
                str(linked_audio),
                1.25,
                0.5,
                7,
                1,
                1_700_000_001.0,
            ),
        )
        connection.execute(
            "INSERT INTO dub_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "dub-1",
                "source.mp4",
                12.0,
                1,
                "English",
                "en",
                tracks,
                job_data,
                "content-sha",
                1_700_000_002.0,
            ),
        )
        connection.execute(
            "INSERT INTO studio_projects VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "project-1",
                "Studio project",
                "../escape.mp4",
                "missing.wav",
                20.0,
                '{"timeline": []}',
                1_700_000_003.0,
                1_700_000_004.0,
            ),
        )
        connection.execute(
            "INSERT INTO export_history VALUES (?, ?, ?, ?, ?)",
            ("export-1", "take.wav", "take.wav", "wav", 1_700_000_005.0),
        )
        connection.execute(
            "INSERT INTO glossary_terms VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("term-1", "project-1", "Galaxy", "Galaxy", "Keep brand", 0, 1.0),
        )
        connection.execute(
            "INSERT INTO pronunciation_entries VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("pron-1", "SQL", "sequel", "respelling", "en", 1, 2.0),
        )
        connection.execute("INSERT INTO settings VALUES ('token', 'private')")
        connection.execute("INSERT INTO jobs VALUES ('job-1', 'running')")
        connection.execute("INSERT INTO job_events VALUES (1, '{}')")
        connection.execute("INSERT INTO future_table VALUES ('new-1', '{}')")
    return source


def build_bundle(tmp_path: Path, members: dict[str, bytes]) -> Path:
    bundle = tmp_path / "portable.ovsvoice"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return bundle


def database_snapshot(source: Path) -> tuple[tuple[object, ...], ...]:
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as connection:
        tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        )
        return tuple(
            (table, *connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone())
            for table in tables
        )


def test_sqlite_rehearsal_is_read_only_and_downgrades_incomplete_consent(
    tmp_path: Path,
) -> None:
    source = build_source_db(
        tmp_path,
        consent_text="I agree",
        consent_recording="missing-consent.wav",
    )
    before = fingerprint_source(source)
    rows_before = database_snapshot(source)

    report = inspect_migration_source(source, approved_roots=(tmp_path,))

    assert report.source_before == before == report.source_after
    assert database_snapshot(source) == rows_before
    assert report.voice_profiles[0].consent.confirmed is False
    assert any("re-attestation" in warning for warning in report.voice_profiles[0].warnings)
    assert not (source.parent / "omnivoice.db-journal").exists()
    assert not (source.parent / "omnivoice.db-wal").exists()


def test_sqlite_maps_supported_groups_and_only_confirms_complete_consent(
    tmp_path: Path,
) -> None:
    source = build_source_db(tmp_path)

    report = inspect_migration_source(source, approved_roots=(tmp_path,))

    voice = report.voice_profiles[0]
    assert voice.source_id == "voice-1"
    assert voice.target == "voice_profile"
    assert voice.data["source"] == "cloned"
    assert voice.data["reference_text"] == "Reference text"
    assert voice.data["instruction"] == "Warm delivery"
    assert voice.consent.confirmed is True
    assert report.generation_history[0].data["starred"] is True
    assert report.dub_history[0].data["tracks"] == [{"speaker": "narrator"}]
    assert report.studio_projects[0].data["name"] == "Studio project"
    assert report.export_history[0].data["filename"] == "take.wav"
    assert report.glossary_terms[0].data["note"] == "Keep brand"
    assert report.pronunciation_entries[0].data["enabled"] is True


def test_asset_states_are_managed_linked_missing_and_unsafe(tmp_path: Path) -> None:
    source = build_source_db(tmp_path)

    report = inspect_migration_source(source, approved_roots=(tmp_path,))

    by_hint = {asset.hint: asset.state for asset in report.assets}
    assert by_hint["reference.wav"] == "managed"
    assert by_hint[str(tmp_path / "linked.wav")] == "linked"
    assert by_hint["missing.wav"] == "missing"
    assert by_hint["../escape.mp4"] == "unsafe"


def test_unknown_schema_and_unsupported_state_are_inventoried(tmp_path: Path) -> None:
    source = build_source_db(tmp_path)
    (source.parent / "runtime.log").write_text("private runtime detail", encoding="utf-8")
    (source.parent / "models").mkdir()
    (source.parent / "models" / "weights.bin").write_bytes(b"weights")

    report = inspect_migration_source(source.parent, approved_roots=(tmp_path,))

    warnings = "\n".join(report.warnings)
    assert "forward-version" in warnings
    assert "future_table" in warnings
    assert "future_profile_field" in warnings
    unsupported = {finding.source for finding in report.unsupported}
    assert {"settings", "jobs", "job_events"} <= unsupported
    assert any("runtime.log" in item for item in unsupported)
    assert any("models" in item for item in unsupported)


@pytest.mark.parametrize("column", ["tracks", "job_data"])
def test_dub_json_is_bounded_before_mapping(tmp_path: Path, column: str) -> None:
    oversized = json.dumps({"payload": "x" * MAX_JSON_BYTES})
    kwargs = {column: oversized}
    source = build_source_db(tmp_path, **kwargs)

    report = inspect_migration_source(source, approved_roots=(tmp_path,))

    assert column not in report.dub_history[0].data
    assert any(
        column in warning and "size limit" in warning
        for warning in report.dub_history[0].warnings
    )


def test_bundle_blocks_traversal_and_cleans_sandbox(tmp_path: Path) -> None:
    bundle = build_bundle(tmp_path, {"../../escape.wav": b"bad"})
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    report = inspect_migration_source(
        bundle,
        approved_roots=(tmp_path,),
        sandbox_root=sandbox,
    )

    assert report.source_before == report.source_after
    assert report.assets[0].state == "unsafe"
    assert not list(sandbox.glob("**/*"))
    assert not (tmp_path.parent / "escape.wav").exists()


def test_bundle_rejects_oversized_members_without_extracting_them(tmp_path: Path) -> None:
    bundle = build_bundle(
        tmp_path,
        {
            "manifest.json": b'{"schema_version": 1, "persona": {"id": "voice-2"}}',
            "preview.wav": b"x" * (MAX_ARCHIVE_MEMBER_BYTES + 1),
        },
    )
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    report = inspect_migration_source(
        bundle,
        approved_roots=(tmp_path,),
        sandbox_root=sandbox,
    )

    preview = next(asset for asset in report.assets if asset.hint == "preview.wav")
    assert preview.state == "unsafe"
    assert any("size limit" in warning for warning in report.warnings)
    assert not list(sandbox.glob("**/*"))


def test_bundle_preserves_checksum_for_declared_missing_asset(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 1,
        "persona": {"id": "voice-2", "name": "Portable voice"},
        "assets": {
            "reference_audio": {
                "path": "missing-reference.wav",
                "sha256": "abc123",
            }
        },
    }
    bundle = build_bundle(
        tmp_path,
        {"manifest.json": json.dumps(manifest).encode("utf-8")},
    )

    report = inspect_migration_source(bundle, approved_roots=(tmp_path,))

    missing = next(asset for asset in report.assets if asset.hint == "missing-reference.wav")
    assert missing.state == "missing"
    assert missing.expected_sha256 == "abc123"


def test_sandbox_inside_directory_source_is_rejected_without_mutating_source(
    tmp_path: Path,
) -> None:
    source = build_source_db(tmp_path).parent
    before = fingerprint_source(source)
    sandbox = source / "sandbox"

    with pytest.raises(ValueError, match="Sandbox root"):
        inspect_migration_source(
            source,
            approved_roots=(tmp_path,),
            sandbox_root=sandbox,
        )

    assert fingerprint_source(source) == before
    assert not sandbox.exists()


def test_directory_discovers_known_documents_without_interpreting_unknown_files(
    tmp_path: Path,
) -> None:
    source = build_source_db(tmp_path)
    copied_root = source.parent
    (copied_root / "transcript.json").write_text(
        json.dumps({"segments": [{"start": 0, "end": 1, "text": "Hello"}]}),
        encoding="utf-8",
    )
    (copied_root / "story.json").write_text(
        json.dumps({"chapters": [{"title": "One", "text": "Opening"}]}),
        encoding="utf-8",
    )
    (copied_root / "unknown.json").write_text('{"arbitrary": true}', encoding="utf-8")

    report = inspect_migration_source(copied_root, approved_roots=(tmp_path,))

    assert {item.target for item in report.discovered_documents} == {
        "transcript_document",
        "longform_document",
    }
    assert any(item.source.endswith("unknown.json") for item in report.unsupported)
