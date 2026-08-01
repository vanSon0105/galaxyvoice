from __future__ import annotations

import shutil
from pathlib import Path


def find_ffmpeg(project_root: Path | None = None) -> str | None:
    root = project_root or Path(__file__).resolve().parents[1]
    bundled = [
        root / "bin" / "ffmpeg.exe",
        root / "bin" / "ffmpeg",
    ]

    for candidate in bundled:
        if candidate.exists():
            return str(candidate)

    return shutil.which("ffmpeg")


def ffmpeg_missing_message(task: str) -> str:
    return (
        f"ffmpeg was not found. Run install_ffmpeg.ps1 in the Galaxy Studio folder, "
        f"or place ffmpeg.exe in bin/ before trying to {task}."
    )
