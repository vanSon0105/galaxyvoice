from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..common.ffmpeg import ffmpeg_missing_message, find_ffmpeg
from ..common.paths import unique_project_dir

ProgressCallback = Callable[[str], None]
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class MediaExtractionOptions:
    video_path: Path
    output_dir: Path
    project_name: str = ""
    export_wav: bool = True
    export_mp3: bool = True


@dataclass(frozen=True)
class MediaExtractionResult:
    project_dir: Path
    wav_path: Path | None
    mp3_path: Path | None
    manifest_path: Path
    warnings: list[str]


def extract_audio_from_video(
    options: MediaExtractionOptions,
    progress: ProgressCallback | None = None,
    ffmpeg_path: str | None = None,
    runner: Runner | None = None,
) -> MediaExtractionResult:
    report = progress or (lambda _message: None)
    video_path = Path(options.video_path).expanduser()
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    if not options.export_wav and not options.export_mp3:
        raise ValueError("Choose at least one audio export format.")

    ffmpeg = ffmpeg_path or find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(ffmpeg_missing_message("extract audio from video"))

    project_name = options.project_name or video_path.stem
    project_dir = unique_project_dir(options.output_dir, project_name, fallback_prefix="media")
    project_slug = project_dir.name
    wav_path = project_dir / f"{project_slug}_audio.wav"
    mp3_path = project_dir / f"{project_slug}_audio.mp3"
    manifest_path = project_dir / "media_manifest.json"
    run = runner or _run_command
    warnings: list[str] = []
    exported_wav: Path | None = None
    exported_mp3: Path | None = None

    if options.export_wav:
        report("Extracting WAV audio...")
        _run_ffmpeg(build_extract_wav_command(ffmpeg, video_path, wav_path), run)
        exported_wav = wav_path

    if options.export_mp3:
        report("Extracting MP3 audio...")
        _run_ffmpeg(build_extract_mp3_command(ffmpeg, video_path, mp3_path), run)
        exported_mp3 = mp3_path

    manifest = {
        "app": "Galaxy AI Voice & Subtitle Studio",
        "version": "0.1.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_video": str(video_path),
        "files": {
            "wav": wav_path.name if exported_wav else None,
            "mp3": mp3_path.name if exported_mp3 else None,
        },
        "notes": [
            "WAV is exported as mono 16 kHz PCM for future speech-to-text alignment.",
            "This extractor does not transcribe speech to SRT by itself.",
        ],
        "warnings": warnings,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report("Done.")

    return MediaExtractionResult(
        project_dir=project_dir,
        wav_path=exported_wav,
        mp3_path=exported_mp3,
        manifest_path=manifest_path,
        warnings=warnings,
    )


def build_extract_wav_command(ffmpeg: str, video_path: Path, output_path: Path) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]


def build_extract_mp3_command(ffmpeg: str, video_path: Path, output_path: Path) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(output_path),
    ]


def _run_ffmpeg(command: list[str], runner: Runner) -> None:
    completed = runner(command)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed while extracting audio."
        raise RuntimeError(message)

    output_path = Path(command[-1])
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg did not create an audio file: {output_path}")


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)
