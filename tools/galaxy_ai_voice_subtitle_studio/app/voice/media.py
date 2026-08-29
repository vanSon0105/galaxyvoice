from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..common.errors import TaskCancelledError
from ..common.ffmpeg import ffmpeg_missing_message, find_ffmpeg
from ..common.paths import unique_project_dir
from ..common.processes import managed_media_processes, terminate_process_tree
from ..reliability.service import estimate_media_working_bytes, guard_output_space

ProgressCallback = Callable[[str], None]
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]

# A wedged or corrupt-input ffmpeg must not hang a worker forever; an hour
# covers multi-hour source videos while still bounding the worst case.
MEDIA_COMMAND_TIMEOUT_SECONDS = 3600


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
    stop_event: threading.Event | None = None,
) -> MediaExtractionResult:
    report = progress or (lambda _message: None)
    video_path = Path(options.video_path).expanduser()
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    if not options.export_wav and not options.export_mp3:
        raise ValueError("Choose at least one audio export format.")

    guard_output_space(
        options.output_dir,
        source_paths=(video_path,),
        required_bytes=estimate_media_working_bytes(
            (video_path,),
            sample_rate=48_000,
            channels=2,
            bytes_per_sample=2,
            working_copies=int(options.export_wav) + int(options.export_mp3),
            minimum_bytes=512 * 1024 * 1024,
        ),
    )

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

    try:
        if options.export_wav:
            report("Extracting WAV audio...")
            _run_ffmpeg(build_extract_wav_command(ffmpeg, video_path, wav_path), run, stop_event=stop_event)
            exported_wav = wav_path

        if options.export_mp3:
            report("Extracting MP3 audio...")
            _run_ffmpeg(build_extract_mp3_command(ffmpeg, video_path, mp3_path), run, stop_event=stop_event)
            exported_mp3 = mp3_path
    except Exception:
        # A failed run must not leave a partial project folder behind.
        shutil.rmtree(project_dir, ignore_errors=True)
        raise

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


def _run_ffmpeg(
    command: list[str],
    runner: Runner,
    stop_event: threading.Event | None = None,
) -> None:
    completed = runner(command) if stop_event is None else runner(command, stop_event=stop_event)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed while extracting audio."
        raise RuntimeError(message)

    output_path = Path(command[-1])
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg did not create an audio file: {output_path}")


def _drain_lines(stream, target: list[str]) -> None:
    """Read a text pipe line by line on a daemon thread so the writer can
    never deadlock on a full pipe buffer while we wait for exit."""
    for line in stream:
        target.append(line)


def _run_command(
    command: list[str],
    *,
    stop_event: threading.Event | None = None,
    timeout: float = MEDIA_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    managed_media_processes.add(process)
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    drainers = [
        threading.Thread(
            target=_drain_lines,
            args=(stream, target),
            name=f"galaxy-drain-{process.pid}",
            daemon=True,
        )
        for stream, target in ((process.stdout, stdout_lines), (process.stderr, stderr_lines))
    ]
    for drainer in drainers:
        drainer.start()
    try:
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    process.wait(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    if stop_event is not None and stop_event.is_set():
                        terminate_process_tree(process)
                        process.wait(timeout=10)
                        raise TaskCancelledError() from None
                    if time.monotonic() > deadline:
                        terminate_process_tree(process)
                        process.wait(timeout=10)
                        raise RuntimeError(
                            f"ffmpeg timed out after {int(timeout)} s: {' '.join(command[:2])}"
                        ) from None
        finally:
            for drainer in drainers:
                drainer.join(timeout=5)
    finally:
        managed_media_processes.discard(process)

    return subprocess.CompletedProcess(
        command,
        process.returncode,
        "".join(stdout_lines),
        "".join(stderr_lines),
    )
