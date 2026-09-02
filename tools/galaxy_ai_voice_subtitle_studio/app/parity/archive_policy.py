"""One archive confinement policy shared by corpus and migration inspection."""

from __future__ import annotations

import stat
import unicodedata
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


_WINDOWS_RESERVED_DEVICE_BASENAMES = frozenset(
    {
        "aux",
        "clock$",
        "con",
        "conin$",
        "conout$",
        "nul",
        "prn",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
        "com\u00b9",
        "com\u00b2",
        "com\u00b3",
        "lpt\u00b9",
        "lpt\u00b2",
        "lpt\u00b3",
    }
)


@dataclass(frozen=True)
class ArchivePolicy:
    max_members: int = 512
    max_member_bytes: int = 8 * 1024 * 1024
    max_total_bytes: int = 128 * 1024 * 1024
    max_compression_ratio: float = 200.0
    read_chunk_bytes: int = 64 * 1024


def validate_archive_members(
    infos: Sequence[zipfile.ZipInfo],
    *,
    policy: ArchivePolicy,
) -> tuple[str, ...]:
    """Validate every member before any archive stream is opened."""
    if len(infos) > policy.max_members:
        raise ValueError("archive member count limit exceeded")
    normalized_names: list[str] = []
    seen_names: set[str] = set()
    total_size = 0
    for info in infos:
        normalized_name = normalized_archive_name(info.filename)
        if normalized_name in seen_names:
            raise ValueError(f"duplicate archive member: {info.filename!r}")
        seen_names.add(normalized_name)
        normalized_names.append(normalized_name)

        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError(f"archive symbolic link: {info.filename!r}")
        file_type = stat.S_IFMT(mode)
        if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise ValueError(f"unsupported archive member type: {info.filename!r}")
        if info.flag_bits & 0x1:
            raise ValueError(f"encrypted archive member: {info.filename!r}")
        if info.file_size < 0 or info.compress_size < 0:
            raise ValueError(f"invalid archive member size: {info.filename!r}")
        if info.is_dir() and (info.file_size or info.compress_size):
            raise ValueError(
                f"archive directory contains payload bytes: {info.filename!r}"
            )
        if info.file_size > policy.max_member_bytes:
            raise ValueError(f"archive member size limit exceeded: {info.filename!r}")
        total_size += info.file_size
        if total_size > policy.max_total_bytes:
            raise ValueError("archive total size limit exceeded")
        compression_ratio = info.file_size / max(info.compress_size, 1)
        if info.file_size and compression_ratio > policy.max_compression_ratio:
            raise ValueError(
                f"archive compression ratio limit exceeded: {info.filename!r}"
            )
    return tuple(normalized_names)


def normalized_archive_name(name: str) -> str:
    if not name:
        raise ValueError("archive member name is empty")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError(f"archive member contains control characters: {name!r}")
    path = PurePosixPath(name)
    if not path.parts or path == PurePosixPath("."):
        raise ValueError(f"invalid archive member path: {name!r}")
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"archive path traversal: {name!r}")
    if PureWindowsPath(name).drive:
        raise ValueError(f"Windows drive archive member path: {name!r}")

    normalized_components: list[str] = []
    for component in path.parts:
        normalized = unicodedata.normalize("NFC", component)
        if ":" in normalized:
            raise ValueError(f"Windows colon archive member path: {name!r}")
        windows_component = normalized.rstrip(" .")
        if not windows_component:
            raise ValueError(f"empty Windows archive member component: {name!r}")
        if windows_component != normalized:
            raise ValueError(f"Windows-normalizing archive member path: {name!r}")
        device_basename = windows_component.split(".", maxsplit=1)[0].casefold()
        if device_basename in _WINDOWS_RESERVED_DEVICE_BASENAMES:
            raise ValueError(f"Windows device archive member path: {name!r}")
        normalized_components.append(windows_component.casefold())
    return "/".join(normalized_components)


def copy_archive_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path | None,
    *,
    policy: ArchivePolicy,
    remaining_total: int,
    check_cancelled: Callable[[], None] | None = None,
) -> int:
    written = 0
    output = destination.open("wb") if destination is not None else None
    try:
        with archive.open(info) as source:
            while chunk := source.read(policy.read_chunk_bytes):
                if check_cancelled is not None:
                    check_cancelled()
                written += len(chunk)
                if written > policy.max_member_bytes:
                    raise ValueError(
                        f"archive member streamed size limit exceeded: {info.filename!r}"
                    )
                if written > remaining_total:
                    raise ValueError("archive streamed total size limit exceeded")
                if output is not None:
                    output.write(chunk)
    finally:
        if output is not None:
            output.close()
    if written != info.file_size:
        raise ValueError(f"archive member size changed while reading: {info.filename!r}")
    return written
