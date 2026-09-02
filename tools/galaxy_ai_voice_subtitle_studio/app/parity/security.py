"""Path, fingerprint, and report-redaction boundaries for parity validation."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from ..common.diagnostics import redact_sensitive_text
from .models import SourceFingerprint


_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|token|secret|password|authorization|credential|cookie)",
    re.IGNORECASE,
)
_HASH_CHUNK_SIZE = 8 * 1024 * 1024
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_GALAXY_ROUTE = re.compile(r"/(?:settings|voice)(?:/[A-Za-z0-9._~-]+)*")


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


def fingerprint_source(
    path: Path,
    *,
    check_cancelled: Callable[[], None] | None = None,
) -> SourceFingerprint:
    if check_cancelled is not None:
        check_cancelled()
    source = Path(path)
    try:
        source_info = source.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Fingerprint source is not a regular file or directory: {path}"
        ) from None
    if _is_link_like(source_info):
        raise UnsafePathError(
            f"Fingerprint source cannot be a link or reparse point: {path}"
        )
    if stat.S_ISREG(source_info.st_mode):
        digest = hashlib.sha256()
        byte_size = _hash_file(source, digest, check_cancelled=check_cancelled)
        return SourceFingerprint(
            kind="file",
            sha256=digest.hexdigest(),
            byte_size=byte_size,
            entry_count=1,
        )
    if stat.S_ISDIR(source_info.st_mode):
        digest = hashlib.sha256(b"directory\0")
        byte_size, entry_count = _hash_directory(
            source,
            digest,
            check_cancelled=check_cancelled,
        )
        return SourceFingerprint(
            kind="directory",
            sha256=digest.hexdigest(),
            byte_size=byte_size,
            entry_count=entry_count,
        )
    raise FileNotFoundError(f"Fingerprint source is not a regular file or directory: {path}")


def _hash_file(
    path: Path,
    digest: Any,
    *,
    check_cancelled: Callable[[], None] | None = None,
) -> int:
    byte_size = 0
    with path.open("rb") as source:
        while chunk := source.read(_HASH_CHUNK_SIZE):
            if check_cancelled is not None:
                check_cancelled()
            digest.update(chunk)
            byte_size += len(chunk)
    return byte_size


def _hash_directory(
    root: Path,
    digest: Any,
    *,
    check_cancelled: Callable[[], None] | None = None,
) -> tuple[int, int]:
    byte_size = 0
    entry_count = 0

    def visit(directory: Path) -> None:
        nonlocal byte_size, entry_count
        if check_cancelled is not None:
            check_cancelled()
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
        for entry in entries:
            if check_cancelled is not None:
                check_cancelled()
            entry_count += 1
            entry_path = Path(entry.path)
            relative_path = entry_path.relative_to(root).as_posix().encode("utf-8")
            entry_info = entry.stat(follow_symlinks=False)
            mode = entry_info.st_mode
            if _is_link_like(entry_info):
                _hash_link_metadata(digest, entry.path, relative_path, entry_info)
            elif stat.S_ISDIR(mode):
                _hash_entry_header(digest, b"D", relative_path)
                visit(entry_path)
            elif stat.S_ISREG(mode):
                _hash_entry_header(digest, b"F", relative_path)
                size = _hash_file(
                    entry_path,
                    digest,
                    check_cancelled=check_cancelled,
                )
                digest.update(b"\0")
                byte_size += size
            else:
                _hash_entry_header(digest, b"O", relative_path)

    visit(root)
    return byte_size, entry_count


def _is_link_like(file_info: os.stat_result) -> bool:
    file_attributes = getattr(file_info, "st_file_attributes", 0)
    return stat.S_ISLNK(file_info.st_mode) or bool(
        _REPARSE_POINT_ATTRIBUTE
        and file_attributes & _REPARSE_POINT_ATTRIBUTE
    )


def _hash_link_metadata(
    digest: Any,
    path: str,
    relative_path: bytes,
    file_info: os.stat_result,
) -> None:
    _hash_entry_header(digest, b"L", relative_path)
    digest.update(str(getattr(file_info, "st_reparse_tag", 0)).encode("ascii"))
    digest.update(b":")
    try:
        target = os.readlink(path)
    except OSError as error:
        raise UnsafePathError(f"Cannot inspect link metadata: {path}") from error
    digest.update(os.fsencode(target))
    digest.update(b"\0")


def _hash_entry_header(digest: Any, kind: bytes, relative_path: bytes) -> None:
    digest.update(kind)
    digest.update(str(len(relative_path)).encode("ascii"))
    digest.update(b":")
    digest.update(relative_path)
    digest.update(b"\0")


def redact_report_value(
    value: Any,
    *,
    approved_roots: Sequence[Path] = (),
) -> Any:
    if isinstance(value, Mapping):
        return {
            _redact_mapping_key(key, approved_roots=approved_roots): (
                "***"
                if _SENSITIVE_KEY.search(str(key))
                else redact_report_value(item, approved_roots=approved_roots)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            redact_report_value(item, approved_roots=approved_roots)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            redact_report_value(item, approved_roots=approved_roots)
            for item in value
        )
    if isinstance(value, str):
        return _redact_absolute_paths(
            _redact_home_prefix(redact_sensitive_text(value)),
            approved_roots=approved_roots,
        )
    return value


def _redact_mapping_key(key: Any, *, approved_roots: Sequence[Path]) -> Any:
    if isinstance(key, str):
        return _redact_absolute_paths(
            _redact_home_prefix(redact_sensitive_text(key)),
            approved_roots=approved_roots,
        )
    return key


def _redact_home_prefix(value: str) -> str:
    home = os.fspath(Path.home())
    variants = (home, home.replace("\\", "/"), home.replace("/", "\\"))
    redacted = value
    for prefix in dict.fromkeys(variants):
        pattern = re.escape(prefix) + r"(?:(?:[\\/])[^\s\"'<>|,;)]*)?"
        redacted = re.sub(pattern, "<home-path>", redacted, flags=re.IGNORECASE)
    return redacted


def _redact_absolute_paths(
    value: str,
    *,
    approved_roots: Sequence[Path],
) -> str:
    redacted = value
    roots = tuple(
        dict.fromkeys(
            str(Path(root).expanduser().resolve(strict=False))
            for root in approved_roots
        )
    )
    for index, root in enumerate(roots, start=1):
        variants = tuple(dict.fromkeys((root, root.replace("\\", "/"), root.replace("/", "\\"))))
        for variant in sorted(variants, key=len, reverse=True):
            pattern = re.escape(variant) + r"(?:(?:[\\/])[^\s\"'<>|,;)]*)?"
            redacted = re.sub(
                pattern,
                f"<external-path:{index}>",
                redacted,
                flags=re.IGNORECASE,
            )
    redacted = re.sub(
        r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/])[^\s\"'<>|,;)]*",
        "<absolute-path>",
        redacted,
    )
    redacted = re.sub(
        r"(?<![.:A-Za-z0-9_])/(?:[^\s/\"'<>|,;)]+/)*[^\s\"'<>|,;)]*",
        lambda match: (
            match.group(0)
            if _GALAXY_ROUTE.fullmatch(match.group(0))
            else "<absolute-path>"
        ),
        redacted,
    )
    return redacted
