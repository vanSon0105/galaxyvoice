from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Callable

from ..common.ffmpeg import ffmpeg_missing_message, find_ffmpeg, find_ffprobe
from ..common.errors import TaskCancelledError
from ..common.paths import unique_project_dir
from ..common.processes import managed_media_processes
from ..reliability.service import guard_output_space
from .plan import RemovalMask, quality_warnings, validate_masks

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
    masks: tuple[RemovalMask, ...] = ()

    @property
    def region(self) -> Region:
        return (
            self.region_x,
            self.region_y,
            self.region_width,
            self.region_height,
        )

    @property
    def resolved_masks(self) -> tuple[RemovalMask, ...]:
        if self.masks:
            return self.masks
        return (RemovalMask("default", "Subtitle area", self.region),)


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
    stop_event: Event | None = None,
    task_id: str | None = None,
) -> SubtitleRemovalResult:
    report = progress or (lambda _message: None)
    source_path = Path(options.video_path).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(f"Video file not found: {source_path}")
    guard_output_space(
        options.output_dir,
        source_paths=(source_path,),
        minimum_mib=512,
        multiplier=1.8,
    )
    if options.mode not in SUBTITLE_REMOVAL_MODES:
        raise ValueError(f"Unknown subtitle removal mode: {options.mode}")
    masks = options.resolved_masks
    if options.mode != STRIP_MODE:
        validate_masks(masks)
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
    run = runner or (
        lambda command: _run_command(command, stop_event=stop_event, task_id=task_id)
    )

    if options.mode != STRIP_MODE and any(
        mask.start_seconds > 0 or mask.end_seconds is not None for mask in masks
    ):
        duration_seconds = probe_video_duration(
            source_path,
            ffprobe_path=ffprobe_path,
            runner=probe_runner,
        )
        validate_masks(masks, duration_seconds)

    if options.mode == STRIP_MODE:
        report("Removing embedded subtitle tracks...")
        command = build_strip_subtitles_command(ffmpeg, source_path, output_path)
    elif options.mode == BLUR_MODE:
        report("Blurring the selected subtitle area...")
        command = build_blur_masks_command(
            ffmpeg,
            source_path,
            output_path,
            masks,
            options.blur_strength,
        )
    elif options.mode == FILL_MODE:
        report("Filling the selected subtitle area...")
        video_size = probe_video_size(
            source_path,
            ffprobe_path=ffprobe_path,
            runner=probe_runner,
        )
        command = build_fill_masks_command(
            ffmpeg,
            source_path,
            output_path,
            masks,
            video_size,
        )
    else:
        raise ValueError(f"Unknown subtitle removal mode: {options.mode}")

    try:
        _check_cancelled(stop_event)
        _run_ffmpeg(command, run, stop_event=stop_event)
    except Exception:
        _cleanup_failed_project(project_dir, output_path, manifest_path)
        raise

    warnings = quality_warnings(options.mode, masks)

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
        "masks": [
            {
                "id": mask.mask_id,
                "name": mask.name,
                "region": {
                    "x": mask.region[0],
                    "y": mask.region[1],
                    "width": mask.region[2],
                    "height": mask.region[3],
                },
                "start_seconds": mask.start_seconds,
                "end_seconds": mask.end_seconds,
            }
            for mask in masks
        ],
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
    return build_blur_masks_command(
        ffmpeg,
        video_path,
        output_path,
        (RemovalMask("default", "Subtitle area", region),),
        blur_strength,
    )


def build_blur_masks_command(
    ffmpeg: str,
    video_path: Path,
    output_path: Path,
    masks: tuple[RemovalMask, ...],
    blur_strength: int,
) -> list[str]:
    validate_masks(masks)
    filters: list[str] = []
    source = "0:v:0"
    for index, mask in enumerate(masks):
        x, y, width, height = (_ratio(value) for value in mask.region)
        base = f"base{index}"
        region = f"region{index}"
        blurred = f"blurred{index}"
        output = "video" if index == len(masks) - 1 else f"masked{index}"
        filters.extend((
            f"[{source}]split=2[{base}][{region}]",
            f"[{region}]crop=w=iw*{width}:h=ih*{height}:x=iw*{x}:y=ih*{y},"
            f"boxblur=luma_radius=min({blur_strength}\\,min(w\\,h)/2-1):luma_power=2:"
            f"chroma_radius=min({blur_strength}\\,min(cw\\,ch)/2-1):chroma_power=2[{blurred}]",
            f"[{base}][{blurred}]overlay=x=main_w*{x}:y=main_h*{y}:shortest=1"
            f"{_enable_filter(mask)}[{output}]",
        ))
        source = output
    filter_graph = ";".join(filters)
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
    return build_fill_masks_command(
        ffmpeg,
        video_path,
        output_path,
        (RemovalMask("default", "Subtitle area", region),),
        video_size,
    )


def build_fill_masks_command(
    ffmpeg: str,
    video_path: Path,
    output_path: Path,
    masks: tuple[RemovalMask, ...],
    video_size: tuple[int, int],
) -> list[str]:
    validate_masks(masks)
    filters = []
    for mask in masks:
        x, y, width, height = _pixel_region(mask.region, video_size)
        filters.append(
            f"delogo=x={x}:y={y}:w={width}:h={height}:show=0{_enable_filter(mask)}"
        )
    video_filter = ",".join(filters)
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
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def _enable_filter(mask: RemovalMask) -> str:
    if mask.start_seconds <= 0 and mask.end_seconds is None:
        return ""
    if mask.end_seconds is None:
        expression = f"gte(t,{mask.start_seconds:.3f})"
    else:
        expression = f"between(t,{mask.start_seconds:.3f},{mask.end_seconds:.3f})"
    return f":enable='{expression}'"


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
    shutil.rmtree(project_dir, ignore_errors=True)


def _run_ffmpeg(
    command: list[str],
    runner: Runner,
    *,
    stop_event: Event | None = None,
) -> None:
    _check_cancelled(stop_event)
    completed = runner(command)
    _check_cancelled(stop_event)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg failed while processing video."
        raise RuntimeError(message)

    output_path = Path(command[-1])
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg did not create a video file: {output_path}")


def _run_command(
    command: list[str],
    *,
    stop_event: Event | None = None,
    task_id: str | None = None,
) -> subprocess.CompletedProcess[str]:
    managed_media_processes.ensure_running()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    managed_media_processes.add(process, task_id=task_id)
    try:
        stdout, stderr = process.communicate()
    finally:
        managed_media_processes.discard(process)
    _check_cancelled(stop_event)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _check_cancelled(stop_event: Event | None) -> None:
    if stop_event is not None and stop_event.is_set():
        raise TaskCancelledError()
