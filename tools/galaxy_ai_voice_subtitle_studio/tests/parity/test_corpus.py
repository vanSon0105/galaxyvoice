from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
import wave
import zipfile
from pathlib import Path

import pytest

import app.parity.corpus as corpus_module
import app.parity.validators as validators_module
from app.parity import AssetInspection, inspect_corpus


def _write_wav(path: Path, *, channels: int = 1, sample_rate: int = 16_000) -> bytes:
    frame_count = sample_rate // 10
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * channels * frame_count)
    return path.read_bytes()


def _write_manifest(root: Path, assets: list[dict[str, object]]) -> Path:
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_id": "test-corpus",
                "created_at": "2026-08-30T00:00:00Z",
                "cases": [
                    {
                        "case_id": "studio.short_tts",
                        "assets": assets,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _asset(role: str, path: str, content: bytes, **extra: object) -> dict[str, object]:
    return {
        "role": role,
        "path": path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "byte_size": len(content),
        **extra,
    }


def test_manifest_reports_each_asset_without_blocking_unrelated_cases(
    tmp_path: Path,
) -> None:
    ready = b"small deterministic fixture"
    (tmp_path / "short.txt").write_bytes(ready)
    manifest = _write_manifest(
        tmp_path,
        [
            _asset("short_tts", "short.txt", ready),
            _asset("long_video", "missing.mp4", b"not-present"),
        ],
    )

    inspection = inspect_corpus(manifest, approved_roots=(tmp_path,))

    assert inspection.assets_by_role["short_tts"].status == "ready"
    assert inspection.assets_by_role["long_video"].status == "missing"


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("sha256", "0" * 64),
        ("byte_size", 999),
    ],
)
def test_manifest_rejects_changed_asset_bytes(
    tmp_path: Path,
    field: str,
    wrong_value: object,
) -> None:
    content = b"pinned"
    (tmp_path / "asset.json").write_bytes(content)
    entry = _asset("batch_manifest", "asset.json", content)
    entry[field] = wrong_value

    inspection = inspect_corpus(
        _write_manifest(tmp_path, [entry]),
        approved_roots=(tmp_path,),
    )

    assert inspection.assets_by_role["batch_manifest"].status == "checksum_mismatch"


def test_manifest_marks_absolute_or_escaping_asset_path_unsafe(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.wav"
    outside.write_bytes(b"outside")
    manifest = _write_manifest(
        tmp_path,
        [
            _asset("absolute", str(outside.resolve()), b"outside"),
            _asset("escape", "../outside.wav", b"outside"),
        ],
    )

    inspection = inspect_corpus(manifest, approved_roots=(tmp_path,))

    assert inspection.assets_by_role["absolute"].status == "unsafe_path"
    assert inspection.assets_by_role["escape"].status == "unsafe_path"


def test_manifest_is_strict_about_unknown_fields(tmp_path: Path) -> None:
    content = b"fixture"
    (tmp_path / "asset.txt").write_bytes(content)
    entry = _asset("short_tts", "asset.txt", content, unexpected=True)

    with pytest.raises(ValueError, match="unexpected"):
        inspect_corpus(
            _write_manifest(tmp_path, [entry]),
            approved_roots=(tmp_path,),
        )


@pytest.mark.parametrize(
    ("duplicate_json", "duplicate_key"),
    [
        (
            '{"schema_version":1,"schema_version":1,"corpus_id":"strict",'
            '"created_at":"2026-08-30T00:00:00Z","cases":[]}',
            "schema_version",
        ),
        (
            '{"schema_version":1,"corpus_id":"strict",'
            '"created_at":"2026-08-30T00:00:00Z","cases":[{'
            '"case_id":"studio.short_tts","assets":[{'
            '"role":"short_tts","path":"one.wav","path":"two.wav",'
            '"sha256":"0000000000000000000000000000000000000000000000000000000000000000",'
            '"byte_size":0}]}]}',
            "path",
        ),
        (
            '{"schema_version":1,"corpus_id":"strict",'
            '"created_at":"2026-08-30T00:00:00Z","cases":[{'
            '"case_id":"studio.short_tts","assets":[{'
            '"role":"short_tts","path":"one.wav",'
            '"sha256":"0000000000000000000000000000000000000000000000000000000000000000",'
            '"byte_size":0,"media":{"container":"wav","container":"wave"}}]}]}',
            "container",
        ),
    ],
)
def test_manifest_rejects_duplicate_json_keys_at_any_nesting(
    tmp_path: Path,
    duplicate_json: str,
    duplicate_key: str,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(duplicate_json, encoding="utf-8")

    with pytest.raises(ValueError, match=rf"Duplicate JSON key: {duplicate_key}"):
        inspect_corpus(manifest, approved_roots=(tmp_path,))


def test_wav_metadata_is_checked_without_external_media_tools(tmp_path: Path) -> None:
    wav_path = tmp_path / "short.wav"
    content = _write_wav(wav_path, channels=1, sample_rate=16_000)
    expected = {
        "container": "wav",
        "audio_codec": "pcm_s16le",
        "audio_streams": 1,
        "channels": 1,
        "sample_rate": 16_000,
    }
    manifest = _write_manifest(
        tmp_path,
        [
            _asset("matching", "short.wav", content, media=expected),
            _asset(
                "wrong_rate",
                "short.wav",
                content,
                media={**expected, "sample_rate": 44_100},
            ),
        ],
    )

    inspection = inspect_corpus(manifest, approved_roots=(tmp_path,))

    assert inspection.assets_by_role["matching"].status == "ready"
    assert inspection.assets_by_role["wrong_rate"].status == "unsupported"


def test_small_structured_fixtures_use_standard_library_probes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "batch.json"
    json_path.write_text('{"items": []}', encoding="utf-8")
    text_path = tmp_path / "script.txt"
    text_path.write_text("Deterministic fixture", encoding="utf-8")
    sqlite_path = tmp_path / "history.sqlite"
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("CREATE TABLE history (id TEXT PRIMARY KEY)")
    bundle_path = tmp_path / "persona.galaxyvoice"
    with zipfile.ZipFile(bundle_path, "w") as archive:
        archive.writestr("manifest.json", '{"schema_version": 1}')

    monkeypatch.setattr(
        "app.parity.validators.find_ffprobe",
        lambda: pytest.fail("small structured fixtures must not invoke ffprobe"),
    )
    assets = [
        _asset("batch", json_path.name, json_path.read_bytes(), media={"container": "json"}),
        _asset("script", text_path.name, text_path.read_bytes(), media={"container": "text"}),
        _asset(
            "history",
            sqlite_path.name,
            sqlite_path.read_bytes(),
            media={"container": "sqlite"},
        ),
        _asset(
            "persona",
            bundle_path.name,
            bundle_path.read_bytes(),
            media={"container": "zip"},
        ),
    ]

    inspection = inspect_corpus(
        _write_manifest(tmp_path, assets),
        approved_roots=(tmp_path,),
    )

    assert {role: item.status for role, item in inspection.assets_by_role.items()} == {
        "batch": "ready",
        "script": "ready",
        "history": "ready",
        "persona": "ready",
    }


@pytest.mark.parametrize(
    "member_name",
    ["../escape.txt", "/absolute.txt", "bad\nname.txt"],
)
def test_zip_probe_rejects_unsafe_member_names(
    tmp_path: Path,
    member_name: str,
) -> None:
    bundle = tmp_path / "unsafe.galaxyvoice"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(member_name, b"unsafe")

    inspection = inspect_corpus(
        _write_manifest(
            tmp_path,
            [_asset("persona", bundle.name, bundle.read_bytes(), media={"container": "zip"})],
        ),
        approved_roots=(tmp_path,),
    )

    assert inspection.assets_by_role["persona"].status == "unsupported"


@pytest.mark.parametrize("unsafe_kind", ["duplicate", "symlink", "directory_payload"])
def test_zip_probe_rejects_duplicate_and_link_members(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    bundle = tmp_path / "unsafe.galaxyvoice"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("safe.txt", b"safe")
        if unsafe_kind == "duplicate":
            archive.writestr("SAFE.TXT", b"duplicate")
        elif unsafe_kind == "symlink":
            link = zipfile.ZipInfo("link.txt")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "safe.txt")
        else:
            archive.writestr("hidden/", b"payload")

    inspection = inspect_corpus(
        _write_manifest(
            tmp_path,
            [_asset("persona", bundle.name, bundle.read_bytes(), media={"container": "zip"})],
        ),
        approved_roots=(tmp_path,),
    )

    assert inspection.assets_by_role["persona"].status == "unsupported"


@pytest.mark.parametrize(
    ("limit_name", "limit", "entries", "compression"),
    [
        ("MAX_ARCHIVE_MEMBERS", 1, [("one.txt", b"1"), ("two.txt", b"2")], zipfile.ZIP_STORED),
        ("MAX_ARCHIVE_MEMBER_BYTES", 4, [("large.txt", b"12345")], zipfile.ZIP_STORED),
        (
            "MAX_ARCHIVE_TOTAL_BYTES",
            5,
            [("one.txt", b"123"), ("two.txt", b"456")],
            zipfile.ZIP_STORED,
        ),
        ("MAX_COMPRESSION_RATIO", 1, [("ratio.txt", b"x" * 1_000)], zipfile.ZIP_DEFLATED),
    ],
)
def test_zip_probe_enforces_resource_limits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    limit_name: str,
    limit: int,
    entries: list[tuple[str, bytes]],
    compression: int,
) -> None:
    monkeypatch.setattr(validators_module, limit_name, limit)
    bundle = tmp_path / "limited.galaxyvoice"
    with zipfile.ZipFile(bundle, "w", compression=compression) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)

    inspection = inspect_corpus(
        _write_manifest(
            tmp_path,
            [_asset("persona", bundle.name, bundle.read_bytes(), media={"container": "zip"})],
        ),
        approved_roots=(tmp_path,),
    )

    assert inspection.assets_by_role["persona"].status == "unsupported"


def test_zip_probe_rejects_metadata_before_opening_member_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "unsafe.galaxyvoice"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("../escape.txt", b"unsafe")
    manifest = _write_manifest(
        tmp_path,
        [_asset("persona", bundle.name, bundle.read_bytes(), media={"container": "zip"})],
    )

    monkeypatch.setattr(
        zipfile.ZipFile,
        "open",
        lambda *args, **kwargs: pytest.fail("unsafe ZIP metadata must fail before CRC streaming"),
    )

    inspection = inspect_corpus(manifest, approved_roots=(tmp_path,))

    assert inspection.assets_by_role["persona"].status == "unsupported"


def test_manifest_rejects_duplicate_roles(tmp_path: Path) -> None:
    content = b"fixture"
    (tmp_path / "asset.txt").write_bytes(content)
    duplicate = _asset("short_tts", "asset.txt", content)

    with pytest.raises(ValueError, match="Duplicate asset role"):
        inspect_corpus(
            _write_manifest(tmp_path, [duplicate, duplicate]),
            approved_roots=(tmp_path,),
        )


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (FileNotFoundError("disappeared"), "missing"),
        (PermissionError("denied"), "unsupported"),
        (OSError("locked"), "unsupported"),
    ],
)
def test_asset_fingerprint_io_error_is_isolated_per_asset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: OSError,
    expected_status: str,
) -> None:
    first = b"first"
    second = b"second"
    (tmp_path / "first.txt").write_bytes(first)
    (tmp_path / "second.txt").write_bytes(second)
    manifest = _write_manifest(
        tmp_path,
        [
            _asset("first", "first.txt", first),
            _asset("second", "second.txt", second),
        ],
    )
    real_fingerprint = corpus_module.fingerprint_source

    def fingerprint(path: Path):
        if path.name == "first.txt":
            raise error
        return real_fingerprint(path)

    monkeypatch.setattr(corpus_module, "fingerprint_source", fingerprint)

    inspection = inspect_corpus(manifest, approved_roots=(tmp_path,))

    assert inspection.assets_by_role["first"].status == expected_status
    assert inspection.assets_by_role["first"].findings[0].message
    assert inspection.assets_by_role["second"].status == "ready"


def test_committed_small_fixture_manifest_is_ready() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures" / "parity"

    inspection = inspect_corpus(
        fixture_root / "manifest.json",
        approved_roots=(fixture_root,),
    )

    assert inspection.assets_by_role["timed_captions"].status == "ready"


def test_asset_inspection_rejects_status_outside_exact_vocabulary() -> None:
    with pytest.raises(ValueError, match="asset status"):
        AssetInspection(role="short_tts", path=None, status="blocked")  # type: ignore[arg-type]
