from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from app.parity import (
    UnsafePathError,
    fingerprint_source,
    redact_report_value,
    resolve_approved_path,
)


def test_approved_path_accepts_descendant_and_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "selected"
    nested = root / "nested" / "source.db"
    nested.parent.mkdir(parents=True)
    nested.touch()

    assert resolve_approved_path(nested, (root,)) == nested.resolve()
    with pytest.raises(UnsafePathError):
        resolve_approved_path(root / ".." / "outside.db", (root,))


def test_approved_path_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "selected"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "external"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symlinks are unavailable: {error}")

    with pytest.raises(UnsafePathError):
        resolve_approved_path(link / "source.db", (root,))


def test_file_fingerprint_hashes_regular_file_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    source.write_bytes(b"native parity")

    fingerprint = fingerprint_source(source)

    assert fingerprint.kind == "file"
    assert fingerprint.sha256 == hashlib.sha256(b"native parity").hexdigest()
    assert fingerprint.byte_size == len(b"native parity")
    assert fingerprint.entry_count == 1


def test_directory_fingerprint_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, names in ((first, ("b.txt", "a.txt")), (second, ("a.txt", "b.txt"))):
        root.mkdir()
        for name in names:
            (root / name).write_text(name, encoding="utf-8")

    assert fingerprint_source(first) == fingerprint_source(second)


def test_directory_fingerprint_does_not_follow_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "source"
    outside = tmp_path / "outside.bin"
    root.mkdir()
    outside.write_bytes(b"outside-one")
    try:
        (root / "external.bin").symlink_to(outside)
    except OSError as error:
        pytest.skip(f"Symlinks are unavailable: {error}")

    before = fingerprint_source(root)

    outside.write_bytes(b"outside-two-is-different")
    assert fingerprint_source(root) == before


def test_redaction_removes_sensitive_values_and_home_prefixes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    source = {
        "api_key": "sk-private-value",
        "nested": [
            {"Authorization": "Bearer private-value"},
            str(home / "media" / "voice.wav"),
        ],
        "tuple": ("safe", {"password": "private-password"}),
    }

    redacted = redact_report_value(source)

    assert redacted == {
        "api_key": "***",
        "nested": [
            {"Authorization": "***"},
            os.fspath(Path("<home>") / "media" / "voice.wav"),
        ],
        "tuple": ("safe", {"password": "***"}),
    }
    assert source["api_key"] == "sk-private-value"
