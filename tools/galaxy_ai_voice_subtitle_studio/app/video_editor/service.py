from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..common.cache import write_json_atomic
from ..common.compute import detect_nvidia_hardware
from ..common.ffmpeg import ffmpeg_missing_message, find_ffmpeg, find_ffprobe
from ..common.paths import unique_project_dir
from ..common.processes import managed_media_processes, terminate_process_tree
from ..reliability.service import estimate_video_working_bytes, guard_output_space
from ..voice.srt import SubtitleCue, parse_srt, render_srt
from .model import normalize_cues

ProgressCallback = Callable[[str], None]

ORIGINAL_RESOLUTION = "original"
RESOLUTION_720P = "720p"
RESOLUTION_1080P = "1080p"
RESOLUTION_2K = "2k"
EDITOR_RESOLUTIONS = {
    ORIGINAL_RESOLUTION: None,
    RESOLUTION_720P: (1280, 720),
    RESOLUTION_1080P: (1920, 1080),
    RESOLUTION_2K: (2560, 1440),
}

SOURCE_FPS = "source"
EDITOR_FPS_OPTIONS = (SOURCE_FPS, "24", "30", "50", "60")

AUTO_ENCODER = "auto"
CPU_ENCODER = "cpu"
NVIDIA_ENCODER = "nvidia"
INTEL_ENCODER = "intel"
EDITOR_ENCODERS = (AUTO_ENCODER, CPU_ENCODER, NVIDIA_ENCODER, INTEL_ENCODER)

MIX_AUDIO = "mix"
REPLACE_AUDIO = "replace"
EDITOR_AUDIO_MODES = (MIX_AUDIO, REPLACE_AUDIO)

# UI label tables exposed through the web settings API.
RESOLUTION_LABELS = {
    ORIGINAL_RESOLUTION: "Theo video gốc",
    RESOLUTION_720P: "HD 720p",
    RESOLUTION_1080P: "Full HD 1080p",
    RESOLUTION_2K: "2K 1440p",
}
FPS_LABELS = {
    SOURCE_FPS: "Theo video gốc",
    "24": "24 fps",
    "30": "30 fps",
    "50": "50 fps",
    "60": "60 fps",
}
ENCODER_LABELS = {
    AUTO_ENCODER: "Tự động",
    CPU_ENCODER: "CPU - libx264",
    NVIDIA_ENCODER: "NVIDIA - NVENC",
    INTEL_ENCODER: "Intel - Quick Sync",
}
AUDIO_MODE_LABELS = {
    MIX_AUDIO: "Trộn với âm thanh gốc",
    REPLACE_AUDIO: "Thay âm thanh gốc",
}

ENCODER_CODEC = {
    CPU_ENCODER: "libx264",
    NVIDIA_ENCODER: "h264_nvenc",
    INTEL_ENCODER: "h264_qsv",
}


@dataclass(frozen=True)
class EditorMediaInfo:
    duration_seconds: float
    width: int
    height: int
    fps: float
    has_audio: bool


@dataclass(frozen=True)
class EditorVideoSegment:
    source_start_ms: int
    source_end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.source_end_ms - self.source_start_ms


@dataclass(frozen=True)
class EditorMediaClip:
    path: Path
    timeline_start_ms: int
    source_start_ms: int
    source_end_ms: int
    track_order: int
    volume: int = 100
    has_audio: bool = True

    @property
    def duration_ms(self) -> int:
        return self.source_end_ms - self.source_start_ms

    @property
    def timeline_end_ms(self) -> int:
        return self.timeline_start_ms + self.duration_ms


@dataclass(frozen=True)
class EditorExportOptions:
    video_path: Path
    output_dir: Path
    project_name: str = ""
    audio_path: Path | None = None
    subtitle_cues: tuple[SubtitleCue, ...] = ()
    audio_offset_ms: int = 0
    audio_mode: str = MIX_AUDIO
    source_volume: int = 100
    external_volume: int = 100
    resolution: str = ORIGINAL_RESOLUTION
    fps: str = SOURCE_FPS
    encoder: str = AUTO_ENCODER
    quality: int = 20
    subtitle_font_size: int = 22
    subtitle_margin: int = 36
    video_segments: tuple[EditorVideoSegment, ...] = ()
    video_clips: tuple[EditorMediaClip, ...] = ()
    audio_clips: tuple[EditorMediaClip, ...] = ()


@dataclass(frozen=True)
class EditorExportResult:
    project_dir: Path
    video_path: Path
    subtitle_path: Path | None
    manifest_path: Path
    warnings: list[str]


def load_editor_subtitles(path: Path, duration_ms: int | None = None) -> list[SubtitleCue]:
    subtitle_path = Path(path).expanduser()
    if not subtitle_path.is_file():
        raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")
    return normalize_cues(parse_srt(subtitle_path.read_text(encoding="utf-8-sig")), duration_ms)


def probe_editor_media(
    media_path: Path,
    ffprobe_path: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> EditorMediaInfo:
    source_path = Path(media_path).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(f"Media file not found: {source_path}")
    ffprobe = ffprobe_path or find_ffprobe()
    if not ffprobe:
        raise RuntimeError("ffprobe was not found. Run install_ffmpeg.ps1 before opening media.")
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(source_path),
    ]
    completed = (runner or subprocess.run)(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "ffprobe could not inspect media."
        raise RuntimeError(detail)
    try:
        payload = json.loads(completed.stdout)
        streams = payload.get("streams", [])
        video = next(stream for stream in streams if stream.get("codec_type") == "video")
        duration = float(payload.get("format", {}).get("duration") or video.get("duration"))
        width = int(video["width"])
        height = int(video["height"])
        fps = _parse_frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
        has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("ffprobe did not return valid video metadata.") from error
    if duration <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("ffprobe returned invalid video metadata.")
    if _video_rotation(video) % 180 == 90:
        width, height = height, width
    return EditorMediaInfo(duration, width, height, fps, has_audio)


def probe_audio_duration(
    media_path: Path,
    ffprobe_path: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> float:
    source_path = Path(media_path).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {source_path}")
    ffprobe = ffprobe_path or find_ffprobe()
    if not ffprobe:
        raise RuntimeError("ffprobe was not found. Run install_ffmpeg.ps1 before opening audio.")
    completed = (runner or subprocess.run)(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "ffprobe could not inspect audio."
        raise RuntimeError(detail)
    try:
        duration = float(completed.stdout.strip())
    except ValueError as error:
        raise RuntimeError("ffprobe did not return a valid audio duration.") from error
    if duration <= 0:
        raise RuntimeError("ffprobe returned an invalid audio duration.")
    return duration


def available_h264_encoders(
    ffmpeg: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> set[str]:
    completed = (runner or subprocess.run)(
        [ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    return {codec for codec in ENCODER_CODEC.values() if re.search(rf"\b{re.escape(codec)}\b", output)}


def resolve_editor_encoder(
    selected: str,
    available: set[str],
    *,
    nvidia_available: bool | None = None,
) -> str:
    normalized = selected.strip().lower()
    if normalized not in EDITOR_ENCODERS:
        normalized = AUTO_ENCODER
    if normalized != AUTO_ENCODER:
        codec = ENCODER_CODEC[normalized]
        if codec not in available:
            raise RuntimeError(f"FFmpeg encoder {codec} is unavailable.")
        return normalized
    has_nvidia = detect_nvidia_hardware() if nvidia_available is None else nvidia_available
    if has_nvidia and ENCODER_CODEC[NVIDIA_ENCODER] in available:
        return NVIDIA_ENCODER
    if os.name == "nt" and ENCODER_CODEC[INTEL_ENCODER] in available:
        return INTEL_ENCODER
    if ENCODER_CODEC[CPU_ENCODER] not in available:
        raise RuntimeError("FFmpeg encoder libx264 is unavailable.")
    return CPU_ENCODER


def build_editor_preview_command(
    ffmpeg: str,
    video_path: Path,
    *,
    start_seconds: float,
    width: int,
    height: int,
    fps: int,
    subtitle_path: Path | None = None,
    subtitle_font_size: int = 18,
    subtitle_margin: int = 24,
) -> list[str]:
    filters: list[str] = []
    if subtitle_path is not None:
        filters.append(
            _subtitle_filter(
                subtitle_path,
                font_size=subtitle_font_size,
                margin=subtitle_margin,
            )
        )
    filters.extend(
        (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
            f"fps={fps}",
        )
    )
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-re",
        "-ss",
        _seconds(start_seconds),
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        ",".join(filters),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]


def build_editor_frame_command(
    ffmpeg: str,
    video_path: Path,
    *,
    position_seconds: float,
    width: int,
    height: int,
    subtitle_path: Path | None = None,
    subtitle_font_size: int = 18,
    subtitle_margin: int = 24,
) -> list[str]:
    command = build_editor_preview_command(
        ffmpeg,
        video_path,
        start_seconds=position_seconds,
        width=width,
        height=height,
        fps=1,
        subtitle_path=subtitle_path,
        subtitle_font_size=subtitle_font_size,
        subtitle_margin=subtitle_margin,
    )
    command.remove("-re")
    output_index = command.index("-f")
    command[output_index:output_index] = ["-frames:v", "1"]
    return command


def build_editor_audio_preview_commands(
    ffplay: str,
    video_path: Path,
    *,
    start_seconds: float,
    source_volume: int,
    audio_path: Path | None,
    audio_offset_ms: int,
    external_volume: int,
    audio_mode: str,
    has_source_audio: bool,
) -> list[list[str]]:
    commands: list[list[str]] = []
    if has_source_audio and (audio_path is None or audio_mode == MIX_AUDIO):
        commands.append(
            _ffplay_audio_command(ffplay, video_path, start_seconds, source_volume, delay_ms=0)
        )
    if audio_path is not None:
        offset_seconds = max(0, audio_offset_ms) / 1000
        if start_seconds >= offset_seconds:
            seek_seconds = start_seconds - offset_seconds
            delay_ms = 0
        else:
            seek_seconds = 0
            delay_ms = round((offset_seconds - start_seconds) * 1000)
        commands.append(
            _ffplay_audio_command(
                ffplay,
                audio_path,
                seek_seconds,
                external_volume,
                delay_ms=delay_ms,
            )
        )
    return commands


def build_editor_export_command(
    ffmpeg: str,
    options: EditorExportOptions,
    media: EditorMediaInfo,
    output_path: Path,
    *,
    encoder: str,
    subtitle_path: Path | str | None,
) -> list[str]:
    if options.resolution not in EDITOR_RESOLUTIONS:
        raise ValueError(f"Unsupported resolution: {options.resolution}")
    if options.fps not in EDITOR_FPS_OPTIONS:
        raise ValueError(f"Unsupported frame rate: {options.fps}")
    if options.audio_mode not in EDITOR_AUDIO_MODES:
        raise ValueError(f"Unsupported audio mode: {options.audio_mode}")
    if options.video_clips:
        return _build_multitrack_export_command(
            ffmpeg,
            options,
            media,
            output_path,
            encoder=encoder,
            subtitle_path=subtitle_path,
        )
    segments = _normalized_video_segments(options.video_segments, media)
    custom_timeline = bool(options.video_segments)
    duration = sum(segment.duration_ms for segment in segments) / 1000
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(options.video_path)]
    if options.audio_path is not None:
        command.extend(["-i", str(options.audio_path)])

    video_filters: list[str] = []
    target_size = EDITOR_RESOLUTIONS[options.resolution]
    if target_size is not None:
        width, height = target_size
        video_filters.extend(
            (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
            )
        )
    elif media.width % 2 or media.height % 2:
        video_filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    if options.fps != SOURCE_FPS:
        video_filters.append(f"fps={int(options.fps)}")
    if subtitle_path is not None:
        video_filters.append(
            _subtitle_filter(
                subtitle_path,
                font_size=options.subtitle_font_size,
                margin=options.subtitle_margin,
            )
        )
    if custom_timeline:
        graph, has_editor_audio = _timeline_filter_graph(
            options,
            media,
            segments,
            video_filters,
            duration,
        )
        command.extend(["-filter_complex", graph, "-map", "[editor_video]"])
        if has_editor_audio:
            command.extend(["-map", "[editor_audio]"])
        else:
            command.append("-an")
    else:
        if video_filters:
            command.extend(["-vf", ",".join(video_filters)])
        command.extend(["-map", "0:v:0"])
        if options.audio_path is not None:
            audio_graph = _audio_filter_graph(options, media)
            command.extend(["-filter_complex", audio_graph, "-map", "[editor_audio]"])
        elif media.has_audio:
            command.extend(
                ["-map", "0:a:0", "-af", f"volume={_volume(options.source_volume)}"]
            )
        else:
            command.append("-an")

    command.extend(_video_encoder_args(encoder, options.quality))
    if options.audio_path is not None or media.has_audio:
        command.extend(["-c:a", "aac", "-b:a", "192k"])
    command.extend(
        [
            "-t",
            _seconds(duration),
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_path),
        ]
    )
    return command


def export_editor_video(
    options: EditorExportOptions,
    progress: ProgressCallback | None = None,
    cancellation: threading.Event | None = None,
    ffmpeg_path: str | None = None,
    task_id: str | None = None,
) -> EditorExportResult:
    report = progress or (lambda _message: None)
    video_path = Path(options.video_path).expanduser()
    if not video_path.is_file():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    if options.audio_path is not None and not Path(options.audio_path).expanduser().is_file():
        raise FileNotFoundError(f"Audio file not found: {options.audio_path}")
    positioned_clips = (*options.video_clips, *options.audio_clips)
    for clip in positioned_clips:
        if not Path(clip.path).expanduser().is_file():
            raise FileNotFoundError(f"Media clip not found: {clip.path}")
    source_paths = tuple(dict.fromkeys(
        [video_path]
        + ([Path(options.audio_path).expanduser()] if options.audio_path is not None else [])
        + [Path(clip.path).expanduser() for clip in positioned_clips]
    ))
    ffmpeg = ffmpeg_path or find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(ffmpeg_missing_message("export an edited video"))

    media = probe_editor_media(video_path)
    segments = _normalized_video_segments(options.video_segments, media)
    timeline_duration_seconds = (
        max(clip.timeline_end_ms for clip in options.video_clips) / 1000
        if options.video_clips
        else sum(segment.duration_ms for segment in segments) / 1000
    )
    target_size = EDITOR_RESOLUTIONS.get(options.resolution) or (media.width, media.height)
    target_fps = media.fps if options.fps == SOURCE_FPS else float(options.fps)
    guard_output_space(
        options.output_dir,
        source_paths=source_paths,
        required_bytes=estimate_video_working_bytes(
            source_paths,
            duration_seconds=timeline_duration_seconds,
            width=target_size[0],
            height=target_size[1],
            fps=target_fps,
        ),
    )
    if (
        not options.video_clips
        and options.audio_path is not None
        and max(0, int(options.audio_offset_ms)) >= round(timeline_duration_seconds * 1000)
    ):
        raise ValueError("Audio phải bắt đầu trước khi video kết thúc.")
    project_dir = unique_project_dir(options.output_dir, options.project_name, "editor")
    output_path = project_dir / f"{project_dir.name}.mp4"
    subtitle_path: Path | None = None
    cues = normalize_cues(list(options.subtitle_cues), round(timeline_duration_seconds * 1000))
    if cues:
        subtitle_path = project_dir / f"{project_dir.name}.srt"
        subtitle_path.write_text(render_srt(cues), encoding="utf-8")
    available = available_h264_encoders(ffmpeg)
    selected_encoder = resolve_editor_encoder(options.encoder, available)
    warnings: list[str] = []
    try:
        report(f"Preparing {options.resolution.upper()} video export...")
        command = build_editor_export_command(
            ffmpeg,
            options,
            media,
            output_path,
            encoder=selected_encoder,
            subtitle_path=subtitle_path.name if subtitle_path else None,
        )
        try:
            _run_export(
                command,
                project_dir,
                timeline_duration_seconds,
                report,
                cancellation,
                task_id=task_id,
            )
        except RuntimeError:
            if cancellation is not None and cancellation.is_set():
                raise
            if options.encoder != AUTO_ENCODER or selected_encoder == CPU_ENCODER:
                raise
            output_path.unlink(missing_ok=True)
            warnings.append(
                f"{ENCODER_CODEC[selected_encoder]} failed; export was retried with CPU libx264."
            )
            report("Hardware encoding failed. Retrying with CPU libx264...")
            if ENCODER_CODEC[CPU_ENCODER] not in available:
                raise RuntimeError("Hardware encoding failed and CPU libx264 is unavailable.")
            fallback = build_editor_export_command(
                ffmpeg,
                options,
                media,
                output_path,
                encoder=CPU_ENCODER,
                subtitle_path=subtitle_path.name if subtitle_path else None,
            )
            _run_export(
                fallback,
                project_dir,
                timeline_duration_seconds,
                report,
                cancellation,
                task_id=task_id,
            )
            selected_encoder = CPU_ENCODER
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not create the edited video.")

        manifest_path = project_dir / "editor_manifest.json"
        write_json_atomic(
            manifest_path,
            {
                "app": "Galaxy AI Voice & Subtitle Studio",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_video": str(video_path),
                "source_audio": str(options.audio_path) if options.audio_path else None,
                "subtitle_cues": len(cues),
                "resolution": options.resolution,
                "fps": options.fps,
                "encoder": selected_encoder,
                "audio_mode": options.audio_mode,
                "audio_offset_ms": max(0, options.audio_offset_ms),
                "video_segments": [
                    {
                        "source_start_ms": segment.source_start_ms,
                        "source_end_ms": segment.source_end_ms,
                    }
                    for segment in segments
                ],
                "video_clips": [_media_clip_manifest(clip) for clip in options.video_clips],
                "audio_clips": [_media_clip_manifest(clip) for clip in options.audio_clips],
                "files": {
                    "video": output_path.name,
                    "subtitle": subtitle_path.name if subtitle_path else None,
                },
            },
        )
        report("Video export complete.")
        return EditorExportResult(project_dir, output_path, subtitle_path, manifest_path, warnings)
    except Exception:
        try:
            for child in project_dir.iterdir():
                if child.is_file():
                    child.unlink(missing_ok=True)
            project_dir.rmdir()
        except OSError:
            pass
        raise


def _media_clip_manifest(clip: EditorMediaClip) -> dict[str, object]:
    return {
        "path": str(clip.path),
        "timeline_start_ms": clip.timeline_start_ms,
        "source_start_ms": clip.source_start_ms,
        "source_end_ms": clip.source_end_ms,
        "track_order": clip.track_order,
        "volume": clip.volume,
        "has_audio": clip.has_audio,
    }


def _run_export(
    command: list[str],
    cwd: Path,
    duration_seconds: float,
    report: ProgressCallback,
    cancellation: threading.Event | None,
    *,
    task_id: str | None = None,
) -> None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    managed_media_processes.add(process, task_id=task_id)
    output: deque[str] = deque(maxlen=80)
    last_percent = -1
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if line:
                    output.append(line)
                if cancellation is not None and cancellation.is_set():
                    terminate_process_tree(process)
                    raise RuntimeError("Video export was stopped.")
                if line.startswith(("out_time_us=", "out_time_ms=")):
                    try:
                        elapsed = int(line.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    percent = min(99, max(0, round(elapsed * 100 / duration_seconds)))
                    if percent != last_percent:
                        report(f"Exporting video... {percent}%")
                        last_percent = percent
        return_code = process.wait()
    except BaseException:
        if process.poll() is None:
            terminate_process_tree(process)
        raise
    finally:
        managed_media_processes.discard(process)
    if return_code != 0:
        detail = "\n".join(output[-30:]) or f"FFmpeg exited with code {return_code}."
        raise RuntimeError(detail)


def _build_multitrack_export_command(
    ffmpeg: str,
    options: EditorExportOptions,
    media: EditorMediaInfo,
    output_path: Path,
    *,
    encoder: str,
    subtitle_path: Path | str | None,
) -> list[str]:
    video_clips = tuple(options.video_clips)
    if not video_clips:
        raise ValueError("At least one video clip is required.")
    for clip in (*video_clips, *options.audio_clips):
        if clip.timeline_start_ms < 0 or clip.source_start_ms < 0 or clip.source_end_ms <= clip.source_start_ms:
            raise ValueError("Invalid positioned media clip.")

    duration_seconds = max(clip.timeline_end_ms for clip in video_clips) / 1000
    target_size = EDITOR_RESOLUTIONS[options.resolution]
    width, height = target_size or (media.width - media.width % 2, media.height - media.height % 2)
    target_fps = int(options.fps) if options.fps != SOURCE_FPS else max(1, round(media.fps))
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for clip in (*video_clips, *options.audio_clips):
        command.extend(["-i", str(clip.path)])

    graph: list[str] = [
        f"color=c=black:s={width}x{height}:r={target_fps}:d={_seconds(duration_seconds)}[video_base]"
    ]
    previous = "video_base"
    indexed_video_clips = sorted(enumerate(video_clips), key=lambda item: item[1].track_order, reverse=True)
    for layer, (input_index, clip) in enumerate(indexed_video_clips):
        clip_label = f"video_clip_{layer}"
        output_label = f"video_layer_{layer}"
        start = _seconds(clip.source_start_ms / 1000)
        end = _seconds(clip.source_end_ms / 1000)
        offset = _seconds(clip.timeline_start_ms / 1000)
        timeline_end = _seconds(clip.timeline_end_ms / 1000)
        graph.append(
            f"[{input_index}:v:0]trim=start={start}:end={end},setpts=PTS-STARTPTS+{offset}/TB,"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[{clip_label}]"
        )
        graph.append(
            f"[{previous}][{clip_label}]overlay=eof_action=pass:shortest=0:"
            f"enable='between(t,{offset},{timeline_end})'[{output_label}]"
        )
        previous = output_label

    video_filters: list[str] = []
    if subtitle_path is not None:
        video_filters.append(
            _subtitle_filter(
                subtitle_path,
                font_size=options.subtitle_font_size,
                margin=options.subtitle_margin,
            )
        )
    video_filters.append("format=yuv420p")
    graph.append(f"[{previous}]{','.join(video_filters)}[editor_video]")

    audio_labels: list[str] = []
    if options.audio_mode == MIX_AUDIO:
        for input_index, clip in enumerate(video_clips):
            if clip.has_audio:
                label = f"video_audio_{input_index}"
                graph.append(_positioned_audio_filter(input_index, clip, label))
                audio_labels.append(f"[{label}]")
    audio_input_offset = len(video_clips)
    for offset_index, clip in enumerate(options.audio_clips):
        input_index = audio_input_offset + offset_index
        label = f"external_audio_{offset_index}"
        graph.append(_positioned_audio_filter(input_index, clip, label))
        audio_labels.append(f"[{label}]")

    duration = _seconds(duration_seconds)
    if len(audio_labels) == 1:
        graph.append(f"{audio_labels[0]}apad,atrim=duration={duration}[editor_audio]")
    elif audio_labels:
        graph.append(
            f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:duration=longest:"
            f"dropout_transition=0:normalize=0,apad,atrim=duration={duration}[editor_audio]"
        )

    command.extend(["-filter_complex", ";".join(graph), "-map", "[editor_video]"])
    if audio_labels:
        command.extend(["-map", "[editor_audio]"])
    else:
        command.append("-an")
    command.extend(_video_encoder_args(encoder, options.quality))
    if audio_labels:
        command.extend(["-c:a", "aac", "-b:a", "192k"])
    command.extend(
        [
            "-t",
            duration,
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_path),
        ]
    )
    return command


def _positioned_audio_filter(input_index: int, clip: EditorMediaClip, label: str) -> str:
    start = _seconds(clip.source_start_ms / 1000)
    end = _seconds(clip.source_end_ms / 1000)
    delay = max(0, int(clip.timeline_start_ms))
    return (
        f"[{input_index}:a:0]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
        f"adelay={delay}:all=1,volume={_volume(clip.volume)}[{label}]"
    )


def _audio_filter_graph(options: EditorExportOptions, media: EditorMediaInfo) -> str:
    duration = _seconds(media.duration_seconds)
    offset = max(0, int(options.audio_offset_ms))
    external = (
        f"[1:a:0]adelay={offset}:all=1,volume={_volume(options.external_volume)},"
        f"apad,atrim=duration={duration}[external_audio]"
    )
    if options.audio_mode == MIX_AUDIO and media.has_audio:
        source = (
            f"[0:a:0]volume={_volume(options.source_volume)},"
            f"apad,atrim=duration={duration}[source_audio]"
        )
        return (
            f"{source};{external};"
            "[source_audio][external_audio]amix=inputs=2:duration=longest:"
            f"dropout_transition=0:normalize=0,atrim=duration={duration}[editor_audio]"
        )
    return f"{external};[external_audio]anull[editor_audio]"


def _normalized_video_segments(
    segments: tuple[EditorVideoSegment, ...],
    media: EditorMediaInfo,
) -> tuple[EditorVideoSegment, ...]:
    source_duration_ms = round(media.duration_seconds * 1000)
    if not segments:
        return (EditorVideoSegment(0, source_duration_ms),)
    normalized: list[EditorVideoSegment] = []
    for segment in segments:
        start = int(segment.source_start_ms)
        end = int(segment.source_end_ms)
        if start < 0 or end <= start or end > source_duration_ms:
            raise ValueError(
                f"Invalid video segment {start}-{end} ms for a {source_duration_ms} ms source."
            )
        normalized.append(EditorVideoSegment(start, end))
    return tuple(normalized)


def _timeline_filter_graph(
    options: EditorExportOptions,
    media: EditorMediaInfo,
    segments: tuple[EditorVideoSegment, ...],
    video_filters: list[str],
    duration_seconds: float,
) -> tuple[str, bool]:
    graph: list[str] = []
    video_labels: list[str] = []
    for index, segment in enumerate(segments):
        label = f"video_segment_{index}"
        graph.append(
            f"[0:v:0]trim=start={_seconds(segment.source_start_ms / 1000)}:"
            f"end={_seconds(segment.source_end_ms / 1000)},setpts=PTS-STARTPTS[{label}]"
        )
        video_labels.append(f"[{label}]")
    if len(video_labels) == 1:
        graph.append(f"{video_labels[0]}null[video_timeline]")
    else:
        graph.append(
            f"{''.join(video_labels)}concat=n={len(video_labels)}:v=1:a=0[video_timeline]"
        )
    video_chain = ",".join(video_filters) if video_filters else "null"
    graph.append(f"[video_timeline]{video_chain}[editor_video]")

    duration = _seconds(duration_seconds)
    source_audio_label: str | None = None
    if media.has_audio and (options.audio_path is None or options.audio_mode == MIX_AUDIO):
        audio_labels: list[str] = []
        for index, segment in enumerate(segments):
            label = f"audio_segment_{index}"
            graph.append(
                f"[0:a:0]atrim=start={_seconds(segment.source_start_ms / 1000)}:"
                f"end={_seconds(segment.source_end_ms / 1000)},asetpts=PTS-STARTPTS[{label}]"
            )
            audio_labels.append(f"[{label}]")
        if len(audio_labels) == 1:
            graph.append(f"{audio_labels[0]}anull[source_timeline_audio]")
        else:
            graph.append(
                f"{''.join(audio_labels)}concat=n={len(audio_labels)}:v=0:a=1[source_timeline_audio]"
            )
        graph.append(
            f"[source_timeline_audio]volume={_volume(options.source_volume)},"
            f"apad,atrim=duration={duration}[source_audio]"
        )
        source_audio_label = "[source_audio]"

    external_audio_label: str | None = None
    if options.audio_path is not None:
        offset = max(0, int(options.audio_offset_ms))
        graph.append(
            f"[1:a:0]adelay={offset}:all=1,volume={_volume(options.external_volume)},"
            f"apad,atrim=duration={duration}[external_audio]"
        )
        external_audio_label = "[external_audio]"

    if source_audio_label and external_audio_label:
        graph.append(
            f"{source_audio_label}{external_audio_label}amix=inputs=2:duration=longest:"
            f"dropout_transition=0:normalize=0,atrim=duration={duration}[editor_audio]"
        )
    elif source_audio_label or external_audio_label:
        graph.append(f"{source_audio_label or external_audio_label}anull[editor_audio]")
    return ";".join(graph), bool(source_audio_label or external_audio_label)


def _video_encoder_args(encoder: str, quality: int) -> list[str]:
    value = max(14, min(32, int(quality)))
    if encoder == NVIDIA_ENCODER:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(value), "-b:v", "0", "-pix_fmt", "yuv420p"]
    if encoder == INTEL_ENCODER:
        return ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", str(value), "-look_ahead", "0", "-pix_fmt", "nv12"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(value), "-pix_fmt", "yuv420p"]


def _subtitle_filter(path: Path | str, *, font_size: int, margin: int) -> str:
    escaped = str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    style = (
        f"FontName=Arial,FontSize={max(10, min(72, int(font_size)))},"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,"
        f"Outline=2,Shadow=0,Alignment=2,MarginV={max(0, min(500, int(margin)))}"
    )
    return f"subtitles=filename='{escaped}':force_style='{style}'"


def _ffplay_audio_command(
    ffplay: str,
    path: Path,
    start_seconds: float,
    volume: int,
    *,
    delay_ms: int,
) -> list[str]:
    audio_filter = f"volume={_volume(volume)}"
    if delay_ms > 0:
        audio_filter = f"adelay={delay_ms}:all=1,{audio_filter}"
    return [
        ffplay,
        "-hide_banner",
        "-loglevel",
        "quiet",
        "-nodisp",
        "-autoexit",
        "-ss",
        _seconds(start_seconds),
        "-af",
        audio_filter,
        str(path),
    ]


def _parse_frame_rate(value: object) -> float:
    text = str(value or "0/1")
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            return float(numerator) / max(float(denominator), 1)
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _video_rotation(stream: dict[str, object]) -> int:
    tags = stream.get("tags")
    if isinstance(tags, dict):
        try:
            return int(float(str(tags.get("rotate", 0))))
        except ValueError:
            pass
    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        for item in side_data:
            if isinstance(item, dict) and "rotation" in item:
                try:
                    return int(float(str(item["rotation"])))
                except ValueError:
                    continue
    return 0


def _volume(percent: int) -> str:
    return f"{max(0, min(200, int(percent))) / 100:.2f}"


def _seconds(value: float) -> str:
    return f"{max(0.0, float(value)):.3f}"
