from __future__ import annotations

import errno
import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from app.parity import (
    UnsafePathError,
    fingerprint_source,
    redact_report_value,
    resolve_approved_path,
)


_SYMLINK_UNAVAILABLE_ERRNOS = {
    errno.EACCES,
    errno.ENOSYS,
    errno.ENOTSUP,
    errno.EPERM,
}
_SYMLINK_UNAVAILABLE_WINERRORS = {1, 50, 1314}


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as error:
        if (
            error.errno in _SYMLINK_UNAVAILABLE_ERRNOS
            or getattr(error, "winerror", None) in _SYMLINK_UNAVAILABLE_WINERRORS
        ):
            pytest.skip(f"Symlinks are unavailable: {error}")
        raise


def _create_windows_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert os.path.isjunction(link)


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
    _symlink_or_skip(link, outside, target_is_directory=True)

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
    _symlink_or_skip(root / "external.bin", outside, target_is_directory=False)

    before = fingerprint_source(root)

    outside.write_bytes(b"outside-two-is-different")
    assert fingerprint_source(root) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_fingerprint_rejects_windows_junction_source(tmp_path: Path) -> None:
    target = tmp_path / "outside"
    junction = tmp_path / "junction"
    target.mkdir()
    _create_windows_junction(junction, target)

    with pytest.raises(UnsafePathError):
        fingerprint_source(junction)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_directory_fingerprint_does_not_follow_windows_junction(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    outside = tmp_path / "outside"
    junction = root / "external"
    root.mkdir()
    outside.mkdir()
    outside_file = outside / "outside.bin"
    outside_file.write_bytes(b"outside-one")
    _create_windows_junction(junction, outside)

    before = fingerprint_source(root)

    assert before.byte_size == 0
    assert before.entry_count == 1
    outside_file.write_bytes(b"outside-two-is-different")
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
