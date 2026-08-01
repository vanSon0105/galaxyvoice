from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .ffmpeg import ffmpeg_missing_message, find_ffmpeg, find_ffprobe
from .paths import unique_project_dir

STRIP_MODE = "strip"
BLUR_MODE = "blur"
FILL_MODE = "fill"
SUBTITLE_REMOVAL_MODES = (STRIP_MODE, BLUR_MODE, FILL_MODE)

ProgressCallback = Callable[[str], None]
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
Region = tuple[int, int, int, int]


@dataclass(frozen=True)
class SubtitleRemovalOptions:
    video_path: Path
    output_dir: Path
    project_name: str = ""
    mode: str = BLUR_MODE
    region_x: int = 5
    region_y: int = 75
    region_width: int = 90
    region_height: int = 20
    blur_strength: int = 18

    @property
    def region(self) -> Region:
        return (
            self.region_x,
            self.region_y,
            self.region_width,
            self.region_height,
        )


@dataclass(frozen=True)
class SubtitleRemovalResult:
    project_dir: Path
    video_path: Path
    manifest_path: Path
    mode: str
    warnings: list[str]


def remove_subtitles_from_video(
    options: SubtitleRemovalOptions,
    progress: ProgressCallback | None = None,
    ffmpeg_path: str | None = None,
    ffprobe_path: str | None = None,
    runner: Runner | None = None,
    probe_runner: Runner | None = None,
) -> SubtitleRemovalResult:
    report = progress or (lambda _message: None)
    source_path = Path(options.video_path).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(f"Video file not found: {source_path}")
    if options.mode not in SUBTITLE_REMOVAL_MODES:
        raise ValueError(f"Unknown subtitle removal mode: {options.mode}")
    if options.mode != STRIP_MODE:
        _validate_region(options.region)
    if not 1 <= options.blur_strength <= 100:
        raise ValueError("Blur strength must be between 1 and 100.")

    ffmpeg = ffmpeg_path or find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(ffmpeg_missing_message("remove subtitles from video"))

    project_name = options.project_name.strip() or f"{source_path.stem}-clean"
    project_dir = unique_project_dir(options.output_dir, project_name, fallback_prefix="clean-video")
    project_slug = project_dir.name
    if options.mode == STRIP_MODE:
        suffix = source_path.suffix.lower() or ".mkv"
    else:
        suffix = ".mp4"
    output_path = project_dir / f"{project_slug}_no_subtitles{suffix}"
    manifest_path = project_dir / "subtitle_removal_manifest.json"
    run = runner or _run_command

    if options.mode == STRIP_MODE:
        report("Removing embedded subtitle tracks...")
        command = build_strip_subtitles_command(ffmpeg, source_path, output_path)
    elif options.mode == BLUR_MODE:
        report("Blurring the selected subtitle area...")
        command = build_blur_subtitles_command(
            ffmpeg,
            source_path,
            output_path,
            options.region,
            options.blur_strength,
        )
    else:
        report("Filling the selected subtitle area...")
        video_size = probe_video_size(
            source_path,
            ffprobe_path=ffprobe_path,
            runner=probe_runner,
        )
        command = build_fill_subtitles_command(
            ffmpeg,
            source_path,
            output_path,
            options.region,
            video_size,
        )

    try:
        _run_ffmpeg(command, run)
    except Exception:
        _cleanup_failed_project(project_dir, output_path, manifest_path)
        raise

    warnings: list[str] = []
    if options.mode == FILL_MODE:
        warnings.append(
            "Smart fill estimates pixels from the edge of the selected area and may leave artifacts on moving backgrounds."
        )

    manifest = {
        "app": "Galaxy AI Voice & Subtitle Studio",
        "version": "0.1.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_video": str(source_path),
        "mode": options.mode,
        "region": {
            "x": options.region_x,
            "y": options.region_y,
            "width": options.region_width,
            "height": options.region_height,
        },
        "blur_strength": options.blur_strength,
        "files": {"video": output_path.name},
        "warnings": warnings,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report("Done.")

    return SubtitleRemovalResult(
        project_dir=project_dir,
        video_path=output_path,
        manifest_path=manifest_path,
        mode=options.mode,
        warnings=warnings,
    )


def create_video_preview(
    video_path: Path,
    output_path: Path,
    timestamp_seconds: float = 0.0,
    ffmpeg_path: str | None = None,
    runner: Runner | None = None,
) -> Path:
    source_path = Path(video_path).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(f"Video file not found: {source_path}")
    ffmpeg = ffmpeg_path or find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(ffmpeg_missing_message("load a video preview"))

    preview_path = Path(output_path)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        build_preview_command(
            ffmpeg,
            source_path,
            preview_path,
            timestamp_seconds=timestamp_seconds,
        ),
        runner or _run_command,
    )
    return preview_path


def build_strip_subtitles_command(ffmpeg: str, video_path: Path, output_path: Path) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-map",
        "0",
        "-map",
        "-0:s",
        "-c",
        "copy",
        str(output_path),
    ]


def build_blur_subtitles_command(
    ffmpeg: str,
    video_path: Path,
    output_path: Path,
    region: Region,
    blur_strength: int,
) -> list[str]:
    x, y, width, height = (_ratio(value) for value in region)
    filter_graph = (
        "[0:v:0]split=2[base][region];"
        f"[region]crop=w=iw*{width}:h=ih*{height}:x=iw*{x}:y=ih*{y},"
        f"boxblur=luma_radius=min({blur_strength}\\,min(w\\,h)/2-1):luma_power=2:"
        f"chroma_radius=min({blur_strength}\\,min(cw\\,ch)/2-1):chroma_power=2[blurred];"
        f"[base][blurred]overlay=x=main_w*{x}:y=main_h*{y}:shortest=1[video]"
    )
    return _build_encoded_command(
        ffmpeg,
        video_path,
        output_path,
        filter_option="-filter_complex",
        filter_value=filter_graph,
        video_map="[video]",
    )


def build_fill_subtitles_command(
    ffmpeg: str,
    video_path: Path,
    output_path: Path,
    region: Region,
    video_size: tuple[int, int],
) -> list[str]:
    x, y, width, height = _pixel_region(region, video_size)
    video_filter = f"delogo=x={x}:y={y}:w={width}:h={height}:show=0"
    return _build_encoded_command(
        ffmpeg,
        video_path,
        output_path,
        filter_option="-vf",
        filter_value=video_filter,
        video_map="0:v:0",
    )


def build_preview_command(
    ffmpeg: str,
    video_path: Path,
    output_path: Path,
    timestamp_seconds: float = 0.0,
) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        _timestamp(timestamp_seconds),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=480:270",
        "-an",
        str(output_path),
    ]


def build_playback_command(
    ffmpeg: str,
    video_path: Path,
    *,
    start_seconds: float,
    width: int,
    height: int,
    fps: int,
) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-re",
        "-ss",
        _timestamp(start_seconds),
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        f"scale={width}:{height},fps={fps}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]


def build_audio_playback_command(ffplay: str, video_path: Path, *, start_seconds: float) -> list[str]:
    return [
        ffplay,
        "-hide_banner",
        "-loglevel",
        "quiet",
        "-nodisp",
        "-autoexit",
        "-ss",
        _timestamp(start_seconds),
        str(video_path),
    ]


def probe_video_size(
    video_path: Path,
    ffprobe_path: str | None = None,
    runner: Runner | None = None,
) -> tuple[int, int]:
    ffprobe = ffprobe_path or find_ffprobe()
    if not ffprobe:
        raise RuntimeError(
            "ffprobe was not found. Run install_ffmpeg.ps1 or place ffprobe.exe in bin before using Smart Fill."
        )
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:stream_tags=rotate:stream_side_data=rotation",
        "-of",
        "json",
        str(video_path),
    ]
    completed = (runner or _run_command)(command)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "ffprobe could not inspect the video."
        raise RuntimeError(message)
    try:
        payload = json.loads(completed.stdout)
        stream = payload["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        rotation = _video_rotation(stream)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("ffprobe did not return a valid video size.") from error
    if width < 1 or height < 1:
        raise RuntimeError("ffprobe returned an invalid video size.")
    if rotation % 180 == 90:
        width, height = height, width
    return width, height


def probe_video_duration(
    video_path: Path,
    ffprobe_path: str | None = None,
    runner: Runner | None = None,
) -> float:
    ffprobe = ffprobe_path or find_ffprobe()
    if not ffprobe:
        raise RuntimeError(
            "ffprobe was not found. Run install_ffmpeg.ps1 or place ffprobe.exe in bin before loading video."
        )
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    completed = (runner or _run_command)(command)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "ffprobe could not inspect the video."
        raise RuntimeError(message)
    try:
        duration = float(completed.stdout.strip())
    except ValueError as error:
        raise RuntimeError("ffprobe did not return a valid video duration.") from error
    if duration <= 0:
        raise RuntimeError("ffprobe returned an invalid video duration.")
    return duration


def _build_encoded_command(
    ffmpeg: str,
    video_path: Path,
    output_path: Path,
    *,
    filter_option: str,
    filter_value: str,
    video_map: str,
) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        filter_option,
        filter_value,
        "-map",
        video_map,
        "-map",
        "0:a?",
        "-map_metadata",
        "0",
        "-sn",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def _validate_region(region: Region) -> None:
    x, y, width, height = region
    if x < 0 or y < 0 or width < 1 or height < 1 or x + width > 100 or y + height > 100:
        raise ValueError("The selected subtitle area must fit inside the video.")


def _ratio(percent: int) -> str:
    return f"{percent / 100:.6f}"


def _timestamp(seconds: float) -> str:
    return f"{max(0.0, float(seconds)):.3f}"


def _pixel_region(region: Region, video_size: tuple[int, int]) -> Region:
    x_percent, y_percent, width_percent, height_percent = region
    video_width, video_height = video_size
    if video_width < 3 or video_height < 3:
        raise RuntimeError("The video is too small for Smart Fill.")

    left = min(video_width - 2, max(1, round(video_width * x_percent / 100)))
    top = min(video_height - 2, max(1, round(video_height * y_percent / 100)))
    right = min(video_width - 1, round(video_width * (x_percent + width_percent) / 100))
    bottom = min(video_height - 1, round(video_height * (y_percent + height_percent) / 100))
    right = max(left + 1, right)
    bottom = max(top + 1, bottom)
    return left, top, right - left, bottom - top


def _video_rotation(stream: object) -> int:
    if not isinstance(stream, dict):
        return 0

    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        for item in side_data:
            if isinstance(item, dict) and "rotation" in item:
                try:
                    return round(float(item["rotation"])) % 360
                except (TypeError, ValueError):
                    pass

    tags = stream.get("tags")
    if isinstance(tags, dict) and "rotate" in tags:
        try:
            return round(float(tags["rotate"])) % 360
        except (TypeError, ValueError):
            pass
    return 0


def _cleanup_failed_project(project_dir: Path, output_path: Path, manifest_path: Path) -> None:
    for path in (output_path, manifest_path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        project_dir.rmdir()
    except OSError:
        pass


def _run_ffmpeg(command: list[str], runner: Runner) -> None:
    completed = runner(command)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed while processing video."
        raise RuntimeError(message)

    output_path = Path(command[-1])
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg did not create a video file: {output_path}")


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)
