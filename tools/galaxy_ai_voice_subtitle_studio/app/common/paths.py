from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path


def studio_root() -> Path:
    """Return the Galaxy Studio tool directory regardless of the caller module."""
    return Path(__file__).resolve().parents[2]


def repository_root() -> Path:
    """Return the workspace repository that contains the tool directory."""
    return studio_root().parents[1]


def unique_project_dir(output_dir: Path, project_name: str, fallback_prefix: str = "galaxy") -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if project_name.strip():
        base_name = slugify(project_name)
    else:
        base_name = datetime.now().strftime(f"{fallback_prefix}_%Y%m%d_%H%M%S")

    candidate = output_dir / base_name
    if not candidate.exists():
        candidate.mkdir(parents=True)
        return candidate

    for suffix in range(2, 10_000):
        candidate = output_dir / f"{base_name}_{suffix:02}"
        if not candidate.exists():
            candidate.mkdir(parents=True)
            return candidate

    raise RuntimeError("Could not create a unique project directory.")


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9._ -]+", "", lowered)
    lowered = re.sub(r"[\s.]+", "-", lowered).strip("-_")
    return lowered or datetime.now().strftime("galaxy_%Y%m%d_%H%M%S")


def same_path(first: Path, second: Path) -> bool:
    """Compare paths without requiring either path to exist."""
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))
