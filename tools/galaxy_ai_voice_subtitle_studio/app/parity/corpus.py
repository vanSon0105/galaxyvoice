"""Strict fixture-manifest parsing and per-asset readiness inspection."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from ..common.errors import TaskCancelledError
from .models import (
    AssetStatus,
    AssetInspection,
    CorpusInspection,
    Finding,
    ManifestAsset,
    ManifestCase,
    MediaExpectation,
    ParityFixtureManifest,
)
from .security import UnsafePathError, fingerprint_source, resolve_approved_path
from .validators import DefaultMediaProbe, MediaProbe, load_strict_json, media_matches


_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MANIFEST_FIELDS = {"schema_version", "corpus_id", "created_at", "cases"}
_CASE_FIELDS = {"case_id", "assets"}
_ASSET_FIELDS = {"role", "path", "sha256", "byte_size", "media"}
_MEDIA_FIELDS = {
    "extension",
    "container",
    "audio_codec",
    "video_codec",
    "audio_streams",
    "video_streams",
    "subtitle_streams",
    "channels",
    "sample_rate",
    "duration_seconds",
}


def inspect_corpus(
    manifest_path: Path,
    *,
    approved_roots: Sequence[Path],
    asset_root: Path | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> CorpusInspection:
    resolved_manifest = resolve_approved_path(manifest_path, approved_roots)
    manifest = _read_manifest(resolved_manifest)
    return inspect_manifest(
        manifest,
        approved_roots=approved_roots,
        asset_root=asset_root or resolved_manifest.parent,
        check_cancelled=check_cancelled,
    )


def inspect_manifest(
    manifest: ParityFixtureManifest,
    *,
    approved_roots: Sequence[Path],
    asset_root: Path,
    check_cancelled: Callable[[], None] | None = None,
) -> CorpusInspection:
    """Inspect assets using an already captured and parsed manifest."""
    assets_by_role: dict[str, AssetInspection] = {}
    roles_by_case: dict[str, tuple[str, ...]] = {}
    probe: MediaProbe = DefaultMediaProbe(check_cancelled=check_cancelled)

    for manifest_case in manifest.cases:
        if check_cancelled is not None:
            check_cancelled()
        roles_by_case[manifest_case.case_id] = tuple(
            asset.role for asset in manifest_case.assets
        )
        for asset in manifest_case.assets:
            if check_cancelled is not None:
                check_cancelled()
            assets_by_role[asset.role] = _inspect_asset(
                asset,
                manifest_root=Path(asset_root).expanduser().resolve(strict=False),
                approved_roots=approved_roots,
                probe=probe,
                check_cancelled=check_cancelled,
            )

    return CorpusInspection(
        manifest=manifest,
        assets_by_role=assets_by_role,
        roles_by_case=roles_by_case,
    )


def _read_manifest(path: Path) -> ParityFixtureManifest:
    try:
        manifest_bytes = path.read_bytes()
    except OSError as error:
        raise ValueError(f"Cannot read parity fixture manifest: {error}") from error
    return parse_manifest_bytes(manifest_bytes)


def parse_manifest_bytes(manifest_bytes: bytes) -> ParityFixtureManifest:
    """Parse the exact manifest bytes captured for a parity run."""
    try:
        payload = load_strict_json(bytes(manifest_bytes).decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ValueError(f"Cannot read parity fixture manifest: {error}") from error
    root = _mapping(payload, "manifest")
    _require_fields(root, _MANIFEST_FIELDS, "manifest")
    schema_version = _integer(root["schema_version"], "schema_version", minimum=1)
    if schema_version != _SCHEMA_VERSION:
        raise ValueError(f"Unsupported manifest schema_version: {schema_version}")
    corpus_id = _nonempty_string(root["corpus_id"], "corpus_id")
    created_at = _nonempty_string(root["created_at"], "created_at")
    raw_cases = _sequence(root["cases"], "cases")

    cases: list[ManifestCase] = []
    seen_case_ids: set[str] = set()
    seen_roles: set[str] = set()
    for case_index, raw_case in enumerate(raw_cases):
        case_payload = _mapping(raw_case, f"cases[{case_index}]")
        _require_fields(case_payload, _CASE_FIELDS, f"cases[{case_index}]")
        case_id = _nonempty_string(
            case_payload["case_id"], f"cases[{case_index}].case_id"
        )
        if case_id in seen_case_ids:
            raise ValueError(f"Duplicate case ID: {case_id}")
        seen_case_ids.add(case_id)
        raw_assets = _sequence(case_payload["assets"], f"cases[{case_index}].assets")
        assets: list[ManifestAsset] = []
        for asset_index, raw_asset in enumerate(raw_assets):
            context = f"cases[{case_index}].assets[{asset_index}]"
            asset_payload = _mapping(raw_asset, context)
            _require_fields(
                asset_payload,
                _ASSET_FIELDS,
                context,
                optional={"media"},
            )
            role = _nonempty_string(asset_payload["role"], f"{context}.role")
            if role in seen_roles:
                raise ValueError(f"Duplicate asset role: {role}")
            seen_roles.add(role)
            sha256 = _nonempty_string(asset_payload["sha256"], f"{context}.sha256")
            if not _SHA256.fullmatch(sha256):
                raise ValueError(f"{context}.sha256 must be lowercase SHA-256")
            media = (
                _parse_media(asset_payload["media"], f"{context}.media")
                if "media" in asset_payload
                else None
            )
            assets.append(
                ManifestAsset(
                    role=role,
                    path=_nonempty_string(asset_payload["path"], f"{context}.path"),
                    sha256=sha256,
                    byte_size=_integer(
                        asset_payload["byte_size"],
                        f"{context}.byte_size",
                        minimum=0,
                    ),
                    media=media,
                )
            )
        cases.append(ManifestCase(case_id=case_id, assets=tuple(assets)))

    return ParityFixtureManifest(
        schema_version=schema_version,
        corpus_id=corpus_id,
        created_at=created_at,
        cases=tuple(cases),
    )


def _parse_media(value: Any, context: str) -> MediaExpectation:
    payload = _mapping(value, context)
    _require_fields(payload, _MEDIA_FIELDS, context, optional=_MEDIA_FIELDS)
    kwargs: dict[str, Any] = {}
    for name in ("extension", "container", "audio_codec", "video_codec"):
        if name in payload:
            kwargs[name] = _nonempty_string(payload[name], f"{context}.{name}")
    for name in (
        "audio_streams",
        "video_streams",
        "subtitle_streams",
        "channels",
        "sample_rate",
    ):
        if name in payload:
            kwargs[name] = _integer(payload[name], f"{context}.{name}", minimum=0)
    if "duration_seconds" in payload:
        duration = payload["duration_seconds"]
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise ValueError(f"{context}.duration_seconds must be a number")
        if not math.isfinite(duration) or duration < 0:
            raise ValueError(f"{context}.duration_seconds must be finite and non-negative")
        kwargs["duration_seconds"] = float(duration)
    return MediaExpectation(**kwargs)


def _inspect_asset(
    asset: ManifestAsset,
    *,
    manifest_root: Path,
    approved_roots: Sequence[Path],
    probe: MediaProbe,
    check_cancelled: Callable[[], None] | None,
) -> AssetInspection:
    relative = Path(asset.path)
    if relative.is_absolute() or ".." in relative.parts:
        return _asset_result(asset, None, "unsafe_path", "unsafe_path", "Asset path must be relative and confined")
    try:
        resolved = resolve_approved_path(manifest_root / relative, approved_roots)
    except UnsafePathError as error:
        return _asset_result(asset, None, "unsafe_path", "unsafe_path", str(error))
    except OSError as error:
        return _asset_io_error(asset, manifest_root / relative, error)
    if not resolved.exists():
        return _asset_result(asset, resolved, "missing", "missing", "Asset file does not exist")
    try:
        fingerprint = fingerprint_source(
            resolved,
            check_cancelled=check_cancelled,
        )
    except UnsafePathError as error:
        return _asset_result(asset, resolved, "unsafe_path", "unsafe_path", str(error))
    except FileNotFoundError as error:
        return _asset_result(asset, resolved, "missing", "missing", str(error))
    except OSError as error:
        return _asset_io_error(asset, resolved, error)
    if fingerprint.kind != "file":
        return _asset_result(asset, resolved, "unsupported", "unsupported", "Manifest assets must be regular files")
    if fingerprint.byte_size != asset.byte_size:
        return _asset_result(asset, resolved, "checksum_mismatch", "byte_size_mismatch", "Asset byte size does not match manifest")
    if fingerprint.sha256 != asset.sha256:
        return _asset_result(asset, resolved, "checksum_mismatch", "checksum_mismatch", "Asset SHA-256 does not match manifest")
    if asset.media is None:
        return AssetInspection(role=asset.role, path=resolved, status="ready")
    try:
        media = probe.inspect(resolved)
    except TaskCancelledError:
        raise
    except FileNotFoundError as error:
        return _asset_result(asset, resolved, "missing", "missing", str(error))
    except OSError as error:
        return _asset_io_error(asset, resolved, error)
    except Exception as error:
        return _asset_result(asset, resolved, "unsupported", "media_probe_failed", str(error))
    mismatches = media_matches(media, asset.media, path=resolved)
    if mismatches:
        return AssetInspection(
            role=asset.role,
            path=resolved,
            status="unsupported",
            findings=tuple(
                Finding(code="media_mismatch", message=mismatch)
                for mismatch in mismatches
            ),
            media=media,
        )
    return AssetInspection(
        role=asset.role,
        path=resolved,
        status="ready",
        media=media,
    )


def _asset_result(
    asset: ManifestAsset,
    path: Path | None,
    status: AssetStatus,
    code: str,
    message: str,
) -> AssetInspection:
    return AssetInspection(
        role=asset.role,
        path=path,
        status=status,
        findings=(Finding(code=code, message=message),),
    )


def _asset_io_error(
    asset: ManifestAsset,
    path: Path,
    error: OSError,
) -> AssetInspection:
    detail = str(error) or type(error).__name__
    return _asset_result(
        asset,
        path,
        "unsupported",
        "asset_io_error",
        f"{type(error).__name__}: {detail}",
    )


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return value


def _sequence(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _require_fields(
    payload: Mapping[str, Any],
    allowed: set[str],
    context: str,
    *,
    optional: set[str] | None = None,
) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"{context} has unexpected fields: {sorted(unknown)}")
    missing = allowed - set(payload) - (optional or set())
    if missing:
        raise ValueError(f"{context} is missing fields: {sorted(missing)}")


def _nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _integer(value: Any, context: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{context} must be an integer >= {minimum}")
    return value
