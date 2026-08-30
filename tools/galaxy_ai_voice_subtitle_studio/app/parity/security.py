"""Path, fingerprint, and report-redaction boundaries for parity validation."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..common.diagnostics import redact_sensitive_text
from .models import SourceFingerprint


_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|token|secret|password|authorization|credential|cookie)",
    re.IGNORECASE,
)
_HASH_CHUNK_SIZE = 8 * 1024 * 1024


class UnsafePathError(ValueError):
    """Raised when a path crosses the explicitly approved local roots."""


def resolve_approved_path(path: Path, roots: Sequence[Path]) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    approved_roots = tuple(
        Path(root).expanduser().resolve(strict=False) for root in roots
    )
    if not approved_roots or not any(
        resolved == root or resolved.is_relative_to(root) for root in approved_roots
    ):
        raise UnsafePathError(f"Path is outside the approved roots: {path}")
    return resolved


def fingerprint_source(path: Path) -> SourceFingerprint:
    source = Path(path)
    if source.is_symlink():
        raise UnsafePathError(f"Fingerprint source cannot be a symlink: {path}")
    if source.is_file():
        digest = hashlib.sha256()
        byte_size = _hash_file(source, digest)
        return SourceFingerprint(
            kind="file",
            sha256=digest.hexdigest(),
            byte_size=byte_size,
            entry_count=1,
        )
    if source.is_dir():
        digest = hashlib.sha256(b"directory\0")
        byte_size, entry_count = _hash_directory(source, digest)
        return SourceFingerprint(
            kind="directory",
            sha256=digest.hexdigest(),
            byte_size=byte_size,
            entry_count=entry_count,
        )
    raise FileNotFoundError(f"Fingerprint source is not a regular file or directory: {path}")


def _hash_file(path: Path, digest: Any) -> int:
    byte_size = 0
    with path.open("rb") as source:
        while chunk := source.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
            byte_size += len(chunk)
    return byte_size


def _hash_directory(root: Path, digest: Any) -> tuple[int, int]:
    byte_size = 0
    entry_count = 0

    def visit(directory: Path) -> None:
        nonlocal byte_size, entry_count
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
        for entry in entries:
            entry_count += 1
            entry_path = Path(entry.path)
            relative_path = entry_path.relative_to(root).as_posix().encode("utf-8")
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                _hash_entry_header(digest, b"L", relative_path)
                digest.update(os.fsencode(os.readlink(entry.path)))
                digest.update(b"\0")
            elif stat.S_ISDIR(mode):
                _hash_entry_header(digest, b"D", relative_path)
                visit(entry_path)
            elif stat.S_ISREG(mode):
                _hash_entry_header(digest, b"F", relative_path)
                size = _hash_file(entry_path, digest)
                digest.update(b"\0")
                byte_size += size
            else:
                _hash_entry_header(digest, b"O", relative_path)

    visit(root)
    return byte_size, entry_count


def _hash_entry_header(digest: Any, kind: bytes, relative_path: bytes) -> None:
    digest.update(kind)
    digest.update(str(len(relative_path)).encode("ascii"))
    digest.update(b":")
    digest.update(relative_path)
    digest.update(b"\0")


def redact_report_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "***" if _SENSITIVE_KEY.search(str(key)) else redact_report_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_report_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_report_value(item) for item in value)
    if isinstance(value, str):
        return _redact_home_prefix(redact_sensitive_text(value))
    return value


def _redact_home_prefix(value: str) -> str:
    home = os.fspath(Path.home())
    variants = (home, home.replace("\\", "/"), home.replace("/", "\\"))
    for prefix in dict.fromkeys(variants):
        if value.casefold() == prefix.casefold():
            return "<home>"
        if len(value) > len(prefix) and value[: len(prefix)].casefold() == prefix.casefold():
            if value[len(prefix)] in ("/", "\\"):
                return f"<home>{value[len(prefix):]}"
    return value
