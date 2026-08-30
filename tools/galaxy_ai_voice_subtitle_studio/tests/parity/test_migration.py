from __future__ import annotations

import io
import json
import os
import random
import sqlite3
import subprocess
import warnings
import wave
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from app.parity import migration as migration_module
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


def valid_wav_bytes(*, frame_count: int = 1600) -> bytes:
    output = io.BytesIO()
    samples = random.Random(1500).randbytes(frame_count * 2)
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(samples)
    return output.getvalue()


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
        (copied_root / name).write_bytes(valid_wav_bytes())
    linked_audio = tmp_path / "linked.wav"
    linked_audio.write_bytes(b"linked")

    source = copied_root / "omnivoice.db"
    with closing(sqlite3.connect(source)) as connection:
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
        connection.commit()
    return source


def build_bundle(tmp_path: Path, members: dict[str, bytes]) -> Path:
    bundle = tmp_path / "portable.ovsvoice"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return bundle


def build_bundle_entries(
    tmp_path: Path,
    entries: list[tuple[str, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> Path:
    bundle = tmp_path / "entries.ovsvoice"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(bundle, "w", compression=compression) as archive:
            for name, payload in entries:
                archive.writestr(name, payload)
    return bundle


def minimal_persona_manifest() -> bytes:
    return json.dumps(
        {
            "format": "ovsvoice",
            "schema_version": 1,
            "persona": {"name": "Bounded voice", "kind": "clone"},
            "members": {"ref_audio": None, "locked_audio": None, "consent_audio": None},
        }
    ).encode("utf-8")


def published_persona_manifest(
    *,
    ref_audio: str | None = "ref_audio.wav",
    locked_audio: str | None = "locked_audio.wav",
    consent_audio: str | None = "consent_audio.wav",
) -> dict[str, object]:
    return {
        "format": "ovsvoice",
        "schema_version": 1,
        "omnivoice_version": "0.4.2",
        "persona": {
            "name": "Published voice",
            "kind": "clone",
            "language": "en",
            "personality": "calm",
            "instruct": "Warm delivery",
            "ref_text": "Reference text",
            "seed": 42,
            "is_locked": True,
            "vd_states": json.dumps({"pitch": "medium"}),
        },
        "engine": {"id": "omnivoice", "design_params": {"style": "warm"}},
        "license": {"spdx": "LicenseRef-Custom", "custom_text": "Local use only"},
        "tags": ["narration", "warm"],
        "preview": {
            "file": "preview.wav",
            "watermarked": True,
            "duration_s": 0.1,
            "sample_rate": 16_000,
        },
        "members": {
            "ref_audio": ref_audio,
            "locked_audio": locked_audio,
            "consent_audio": consent_audio,
        },
    }


def published_consent() -> dict[str, object]:
    return {
        "verified_own_voice": True,
        "method": "self-recorded-statement",
        "consent_text": "I attest this is my voice",
        "recorded_at": 1_700_000_000.0,
        "has_recording": True,
    }


def database_snapshot(source: Path) -> tuple[tuple[object, ...], ...]:
    with closing(
        sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    ) as connection:
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


@pytest.mark.parametrize(
    ("verified", "recorded_at"),
    [("false", 1_700_000_000.0), (1, ""), (1, "not-a-timestamp")],
)
def test_sqlite_consent_rejects_noncanonical_boolean_and_timestamp(
    tmp_path: Path,
    verified: object,
    recorded_at: object,
) -> None:
    source = build_source_db(tmp_path)
    with closing(sqlite3.connect(source)) as connection:
        connection.execute(
            "UPDATE voice_profiles SET verified_own_voice = ?, consent_recorded_at = ?",
            (verified, recorded_at),
        )
        connection.commit()

    report = inspect_migration_source(source, approved_roots=(tmp_path,))

    assert report.voice_profiles[0].consent.confirmed is False
    assert any("re-attestation" in item for item in report.voice_profiles[0].warnings)


def test_sqlite_consent_rejects_file_with_audio_extension_but_invalid_content(
    tmp_path: Path,
) -> None:
    source = build_source_db(tmp_path)
    (source.parent / "consent.wav").write_bytes(b"not an audio stream" * 100)

    report = inspect_migration_source(source, approved_roots=(tmp_path,))

    assert report.voice_profiles[0].consent.confirmed is False


def test_bundle_consent_rejects_truthy_strings_arbitrary_method_and_fake_audio(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(
        tmp_path,
        {
            "manifest.json": json.dumps(
                {"schema_version": 1, "persona": {"id": "voice-unsafe"}}
            ).encode("utf-8"),
            "consent.json": json.dumps(
                {
                    "verified": "false",
                    "method": "anything",
                    "statement": "I agree",
                    "timestamp": "anything",
                }
            ).encode("utf-8"),
            "consent_audio.txt": b"not audio" * 200,
        },
    )

    report = inspect_migration_source(bundle, approved_roots=(tmp_path,))

    assert report.persona_bundles[0].consent.confirmed is False
    assert report.persona_bundles[0].consent.basis == ""


def test_sqlite_wal_copy_is_rejected_before_sidecars_can_change(tmp_path: Path) -> None:
    source = build_source_db(tmp_path)
    writer = sqlite3.connect(source)
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        writer.execute("INSERT INTO settings VALUES ('wal-row', 'value')")
        writer.commit()
        sidecars = (Path(f"{source}-wal"), Path(f"{source}-shm"))
        assert all(path.is_file() for path in sidecars)
        source_before = fingerprint_source(source.parent)
        sidecars_before = {path.name: path.read_bytes() for path in sidecars}

        with pytest.raises(ValueError, match="WAL|sidecar"):
            inspect_migration_source(source, approved_roots=(tmp_path,))

        assert fingerprint_source(source.parent) == source_before
        assert {path.name: path.read_bytes() for path in sidecars} == sidecars_before
    finally:
        writer.close()


def test_sqlite_sidecar_created_during_inspection_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = build_source_db(tmp_path)
    real_inspect = migration_module._inspect_database

    def inspect_then_create_sidecar(*args: object, **kwargs: object) -> None:
        real_inspect(*args, **kwargs)
        Path(f"{source}-wal").write_bytes(b"unexpected sidecar")

    monkeypatch.setattr(migration_module, "_inspect_database", inspect_then_create_sidecar)

    with pytest.raises(ValueError, match="WAL|sidecar"):
        inspect_migration_source(source, approved_roots=(tmp_path,))


def test_sqlite_connection_is_closed_and_copy_can_be_replaced_immediately(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = build_source_db(tmp_path)
    real_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    def track_connection(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(migration_module.sqlite3, "connect", track_connection)

    inspect_migration_source(source, approved_roots=(tmp_path,))

    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")
    replacement = source.with_name("replacement.db")
    source.rename(replacement)
    replacement.unlink()


def test_asset_states_are_managed_linked_missing_and_unsafe(tmp_path: Path) -> None:
    source = build_source_db(tmp_path)

    report = inspect_migration_source(source, approved_roots=(tmp_path,))

    by_hint = {asset.hint: asset.state for asset in report.assets}
    assert by_hint["reference.wav"] == "managed"
    linked = next(asset for asset in report.assets if asset.role == "generated_audio")
    assert linked.state == "linked"
    assert str(tmp_path) not in linked.hint
    assert by_hint["missing.wav"] == "missing"
    assert by_hint["../escape.mp4"] == "unsafe"


def test_absolute_asset_hints_are_redacted_after_classification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = build_source_db(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    linked = fake_home / "linked.wav"
    linked.write_bytes(valid_wav_bytes())
    with closing(sqlite3.connect(source)) as connection:
        connection.execute(
            "UPDATE generation_history SET audio_path = ?",
            (str(linked),),
        )
        connection.commit()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    report = inspect_migration_source(source, approved_roots=(tmp_path,))

    asset = next(item for item in report.assets if item.role == "generated_audio")
    assert asset.state == "linked"
    assert asset.hint.replace("\\", "/") == "<home>/linked.wav"
    assert str(fake_home) not in repr(report)


def test_global_report_warnings_are_redacted() -> None:
    fingerprint = migration_module.SourceFingerprint("file", "abc", 1, 1)
    report = migration_module.MigrationDryRun(
        source_before=fingerprint,
        source_after=fingerprint,
        warnings=(f"failed under {Path.home()} with api_key=TOP-SECRET",),
    )

    warning = report.warnings[0]
    assert str(Path.home()) not in warning
    assert "TOP-SECRET" not in warning


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


def test_settings_json_and_sensitive_payload_are_unsupported_and_never_returned(
    tmp_path: Path,
) -> None:
    source = build_source_db(tmp_path)
    settings = source.parent / "settings.json"
    settings.write_text(
        json.dumps({"items": [], "api_key": "TOP-SECRET", "token": "PRIVATE"}),
        encoding="utf-8",
    )

    report = inspect_migration_source(source.parent, approved_roots=(tmp_path,))

    assert not any(item.source_id == "settings.json" for item in report.discovered_documents)
    assert any(item.source == "settings.json" for item in report.unsupported)
    assert "TOP-SECRET" not in repr(report)
    assert "PRIVATE" not in repr(report)


def test_dub_mapping_allowlists_structure_and_classifies_output_assets(
    tmp_path: Path,
) -> None:
    source = build_source_db(tmp_path)
    (source.parent / "dub-output.wav").write_bytes(valid_wav_bytes())
    (source.parent / "final.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 128)
    (source.parent / "source.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"1" * 128)
    segment = {
        "id": "seg-1",
        "start": 0.0,
        "end": 1.0,
        "text": "Hola",
        "speaker": "A",
        "engine_cache": "SEGMENT-SECRET",
    }
    tracks = [
        {
            "id": "track-es",
            "language": "Spanish",
            "language_code": "es",
            "output_path": "dub-output.wav",
            "segments": [segment],
            "engine_cache": {"api_key": "TRACK-SECRET"},
        }
    ]
    job_data = {
        "target_language": "es",
        "final_output_path": "final.mp4",
        "source_path": "source.mp4",
        "segments": [segment],
        "api_key": "JOB-SECRET",
        "model_cache": {"token": "CACHE-SECRET"},
    }
    with closing(sqlite3.connect(source)) as connection:
        connection.execute(
            "UPDATE dub_history SET tracks = ?, job_data = ?",
            (json.dumps(tracks), json.dumps(job_data)),
        )
        connection.commit()

    report = inspect_migration_source(source, approved_roots=(tmp_path,))

    candidate = report.dub_history[0]
    assert candidate.data["tracks"] == [
        {
            "id": "track-es",
            "language": "Spanish",
            "language_code": "es",
            "segments": [
                {"id": "seg-1", "start": 0.0, "end": 1.0, "text": "Hola", "speaker": "A"}
            ],
        }
    ]
    assert candidate.data["job"] == {
        "target_language": "es",
        "segments": [
            {"id": "seg-1", "start": 0.0, "end": 1.0, "text": "Hola", "speaker": "A"}
        ],
    }
    assert {asset.hint for asset in candidate.assets} >= {
        "dub-output.wav",
        "final.mp4",
        "source.mp4",
    }
    assert all(asset.state == "managed" for asset in candidate.assets)
    assert any("unsupported" in warning.casefold() for warning in candidate.warnings)
    assert "SECRET" not in repr(candidate)


def test_studio_state_is_allowlisted_and_unmatched_fields_warn(tmp_path: Path) -> None:
    source = build_source_db(tmp_path)
    state = {
        "language": "en",
        "timeline": [
            {
                "id": "clip-1",
                "start": 0,
                "end": 1,
                "text": "Hello",
                "api_key": "CLIP-SECRET",
            }
        ],
        "output_path": "take.wav",
        "engine_cache": {"token": "STATE-SECRET"},
        "api_key": "PROJECT-SECRET",
    }
    with closing(sqlite3.connect(source)) as connection:
        connection.execute(
            "UPDATE studio_projects SET state_json = ?",
            (json.dumps(state),),
        )
        connection.commit()

    report = inspect_migration_source(source, approved_roots=(tmp_path,))

    candidate = report.studio_projects[0]
    assert candidate.data["state"] == {
        "language": "en",
        "timeline": [
            {"id": "clip-1", "start": 0, "end": 1, "text": "Hello"}
        ],
    }
    assert any(asset.role == "studio_output" and asset.hint == "take.wav" for asset in candidate.assets)
    assert any("unsupported" in warning.casefold() for warning in candidate.warnings)
    assert "SECRET" not in repr(candidate)


def test_unsafe_export_is_not_emitted_as_import_candidate(tmp_path: Path) -> None:
    source = build_source_db(tmp_path)
    with closing(sqlite3.connect(source)) as connection:
        connection.execute(
            "UPDATE export_history SET destination_path = '../escape.wav'"
        )
        connection.commit()

    report = inspect_migration_source(source, approved_roots=(tmp_path,))

    assert report.export_history == ()
    assert any("export-1" in warning and "unsafe" in warning for warning in report.warnings)


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


def test_archive_member_count_limit_rejects_whole_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(migration_module, "MAX_ARCHIVE_MEMBERS", 3)
    bundle = build_bundle_entries(
        tmp_path,
        [
            ("manifest.json", minimal_persona_manifest()),
            ("preview.wav", valid_wav_bytes()),
            ("extra-1.txt", b"one"),
            ("extra-2.txt", b"two"),
        ],
        compression=zipfile.ZIP_STORED,
    )

    report = inspect_migration_source(bundle, approved_roots=(tmp_path,))

    assert report.persona_bundles == ()
    assert not any(asset.state == "managed" for asset in report.assets)
    assert any("member count" in warning for warning in report.warnings)


def test_archive_total_size_limit_rejects_whole_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(migration_module, "MAX_ARCHIVE_TOTAL_BYTES", 1024)
    bundle = build_bundle_entries(
        tmp_path,
        [
            ("manifest.json", minimal_persona_manifest()),
            ("preview.wav", valid_wav_bytes()),
        ],
        compression=zipfile.ZIP_STORED,
    )

    report = inspect_migration_source(bundle, approved_roots=(tmp_path,))

    assert report.persona_bundles == ()
    assert not any(asset.state == "managed" for asset in report.assets)
    assert any("total size" in warning for warning in report.warnings)


@pytest.mark.parametrize(
    "entries",
    [
        [
            ("manifest.json", minimal_persona_manifest()),
            ("manifest.json", minimal_persona_manifest()),
            ("preview.wav", valid_wav_bytes()),
        ],
        [
            ("manifest.json", minimal_persona_manifest()),
            ("preview.wav", valid_wav_bytes()),
            ("bad\nname.wav", valid_wav_bytes()),
        ],
    ],
)
def test_archive_duplicate_or_control_member_rejects_whole_bundle(
    tmp_path: Path,
    entries: list[tuple[str, bytes]],
) -> None:
    bundle = build_bundle_entries(tmp_path, entries, compression=zipfile.ZIP_STORED)

    report = inspect_migration_source(bundle, approved_roots=(tmp_path,))

    assert report.persona_bundles == ()
    assert not any(asset.state == "managed" for asset in report.assets)


def test_archive_compression_ratio_limit_rejects_whole_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(migration_module, "MAX_COMPRESSION_RATIO", 2)
    bundle = build_bundle_entries(
        tmp_path,
        [
            ("manifest.json", minimal_persona_manifest()),
            ("preview.wav", b"x" * 20_000),
        ],
    )

    report = inspect_migration_source(bundle, approved_roots=(tmp_path,))

    assert report.persona_bundles == ()
    assert not any(asset.state == "managed" for asset in report.assets)
    assert any("compression ratio" in warning for warning in report.warnings)


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


def test_published_persona_shape_maps_identity_metadata_members_and_consent(
    tmp_path: Path,
) -> None:
    bundle = build_bundle_entries(
        tmp_path,
        [
            ("manifest.json", json.dumps(published_persona_manifest()).encode("utf-8")),
            ("consent.json", json.dumps(published_consent()).encode("utf-8")),
            ("preview.wav", valid_wav_bytes()),
            ("ref_audio.wav", valid_wav_bytes()),
            ("locked_audio.wav", valid_wav_bytes()),
            ("consent_audio.wav", valid_wav_bytes()),
        ],
        compression=zipfile.ZIP_STORED,
    )

    report = inspect_migration_source(bundle, approved_roots=(tmp_path,))

    candidate = report.persona_bundles[0]
    assert candidate.data["name"] == "Published voice"
    assert candidate.data["personality"] == "calm"
    assert candidate.data["seed"] == 42
    assert candidate.data["is_locked"] is True
    assert candidate.data["design_state"] == {"pitch": "medium"}
    assert candidate.data["engine_id"] == "omnivoice"
    assert candidate.data["design_params"] == {"style": "warm"}
    assert candidate.data["tags"] == ["narration", "warm"]
    assert candidate.data["license_spdx"] == "LicenseRef-Custom"
    assert candidate.data["license_custom_text"] == "Local use only"
    assert candidate.data["preview"] == {
        "file": "preview.wav",
        "watermarked": True,
        "duration_s": 0.1,
        "sample_rate": 16_000,
    }
    assert candidate.data["verified_own_voice_evidence"] is True
    assert candidate.consent.confirmed is True
    assert {asset.role for asset in candidate.assets} >= {
        "reference_audio",
        "locked_audio",
        "consent_recording",
        "preview",
    }


def test_published_persona_declared_missing_member_is_relink_candidate(
    tmp_path: Path,
) -> None:
    manifest = published_persona_manifest(
        ref_audio="missing-reference.wav",
        locked_audio=None,
        consent_audio=None,
    )
    bundle = build_bundle_entries(
        tmp_path,
        [
            ("manifest.json", json.dumps(manifest).encode("utf-8")),
            ("preview.wav", valid_wav_bytes()),
        ],
        compression=zipfile.ZIP_STORED,
    )

    report = inspect_migration_source(bundle, approved_roots=(tmp_path,))

    missing = next(
        asset for asset in report.persona_bundles[0].assets if asset.hint == "missing-reference.wav"
    )
    assert missing.role == "reference_audio"
    assert missing.state == "missing"


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


@pytest.mark.parametrize(
    ("environment", "relative_root"),
    [
        ("LOCALAPPDATA", Path("GalaxyAIStudio/models/VoiceStudio/data")),
        ("APPDATA", Path("OmniVoice")),
        ("OMNIVOICE_DATA_DIR", Path("")),
    ],
)
def test_live_galaxy_and_voicestudio_roots_are_rejected_even_when_approved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment: str,
    relative_root: Path,
) -> None:
    source = build_source_db(tmp_path)
    environment_root = tmp_path / f"live-{environment.casefold()}"
    monkeypatch.setenv(environment, str(environment_root))
    live_root = environment_root / relative_root
    live_root.mkdir(parents=True)
    live_database = live_root / "omnivoice.db"
    source.replace(live_database)

    with pytest.raises(ValueError, match="live|protected|copied"):
        inspect_migration_source(live_database, approved_roots=(tmp_path,))


def test_repository_and_vendor_paths_are_rejected_before_format_detection() -> None:
    tool_root = Path(__file__).resolve().parents[2]
    vendor_file = tool_root / "vendor" / "voicestudio" / "pyproject.toml"

    with pytest.raises(ValueError, match="repository|vendor|protected"):
        inspect_migration_source(vendor_file, approved_roots=(tool_root.parents[1],))


def test_renamed_sqlite_file_is_not_a_typed_voicestudio_copy(tmp_path: Path) -> None:
    source = build_source_db(tmp_path)
    renamed = source.with_name("arbitrary.db")
    source.rename(renamed)

    with pytest.raises(ValueError, match="omnivoice.db|copied|source type"):
        inspect_migration_source(renamed, approved_roots=(tmp_path,))


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_top_level_junction_source_is_rejected_before_resolution(tmp_path: Path) -> None:
    target = build_source_db(tmp_path).parent
    junction = tmp_path / "selected-copy"
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert os.path.isjunction(junction)

    with pytest.raises(ValueError, match="link|reparse"):
        inspect_migration_source(junction, approved_roots=(tmp_path,))


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


def test_discovery_rejects_invalid_signatures_and_empty_structures(tmp_path: Path) -> None:
    source = build_source_db(tmp_path)
    copied_root = source.parent
    (copied_root / "empty-transcript.json").write_text(
        json.dumps({"segments": []}), encoding="utf-8"
    )
    (copied_root / "fake.pdf").write_bytes(b"not a PDF")
    (copied_root / "fake.wav").write_bytes(b"not audio")

    report = inspect_migration_source(copied_root, approved_roots=(tmp_path,))

    unsupported = {item.source for item in report.unsupported}
    assert {"empty-transcript.json", "fake.pdf", "fake.wav"} <= unsupported
    assert not {
        "empty-transcript.json",
        "fake.pdf",
        "fake.wav",
    } & {item.source_id for item in report.discovered_documents}


def test_discovery_validates_srt_pdf_epub_and_media_and_emits_media_asset(
    tmp_path: Path,
) -> None:
    source = build_source_db(tmp_path)
    copied_root = source.parent
    (copied_root / "captions.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
        encoding="utf-8",
    )
    (copied_root / "book.pdf").write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF")
    with zipfile.ZipFile(copied_root / "book.epub", "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", "<container/>")
    (copied_root / "generated.wav").write_bytes(valid_wav_bytes())

    report = inspect_migration_source(copied_root, approved_roots=(tmp_path,))

    by_source = {item.source_id: item for item in report.discovered_documents}
    assert by_source["captions.srt"].data["cue_count"] == 1
    assert by_source["book.pdf"].data["format"] == "pdf"
    assert by_source["book.epub"].data["format"] == "epub"
    generated = by_source["generated.wav"]
    assert generated.target == "generated_asset"
    assert generated.assets == (
        migration_module.MigrationAsset(
            role="generated_media",
            hint="generated.wav",
            state="managed",
            byte_size=(copied_root / "generated.wav").stat().st_size,
        ),
    )
