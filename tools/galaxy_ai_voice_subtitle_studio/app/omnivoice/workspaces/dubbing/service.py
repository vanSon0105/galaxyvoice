from __future__ import annotations

import subprocess
import threading
from dataclasses import asdict, replace
from pathlib import Path
from typing import Mapping

from ....common.cache import read_json, write_json_atomic
from ....common.ffmpeg import find_ffmpeg, find_ffprobe, ffmpeg_missing_message
from ....reliability.service import guard_output_space
from ....voice.media import _run_command, _run_ffmpeg
from ...models import OmniVoiceGenerationOptions
from ...profiles import VoiceProfile
from ...service import WorkerClient
from ..renderer import LongformWorkspaceResult, render_longform_plan
from .model import (
    DubbingFitPolicy,
    DubbingSegment,
    build_dubbing_quality_report,
    plan_dubbing_segments,
)


MIX_REPLACE = "replace"
MIX_SOURCE = "mix"
MIX_DUCK = "duck"
MIX_MODES = frozenset({MIX_REPLACE, MIX_SOURCE, MIX_DUCK})


def render_dubbing_project(
    base_options: OmniVoiceGenerationOptions,
    segments: tuple[DubbingSegment, ...],
    client: WorkerClient,
    *,
    profiles: tuple[VoiceProfile, ...] = (),
    cast_map: Mapping[str, str] | None = None,
    fit_policy: DubbingFitPolicy | None = None,
    export_mp3: bool = True,
    export_stems: bool = True,
    source_video: Path | None = None,
    source_audio: Path | None = None,
    mix_mode: str = MIX_REPLACE,
    source_volume: float = 0.25,
    dub_volume: float = 1.0,
    progress=None,
    resume_project_dir: Path | None = None,
    stop_event: threading.Event | None = None,
) -> LongformWorkspaceResult:
    source_paths = tuple(
        path for path in (source_video, source_audio) if path is not None
    )
    guard_output_space(
        base_options.output_dir,
        source_paths=source_paths,
        minimum_mib=512,
        multiplier=2.0,
    )
    policy = fit_policy or DubbingFitPolicy()
    normalized_mode = mix_mode.strip().lower() or MIX_REPLACE
    if normalized_mode not in MIX_MODES:
        raise ValueError(f"Chế độ trộn audio không hợp lệ: {mix_mode}")
    _validate_optional_file(source_video, "video nguồn")
    _validate_optional_file(source_audio, "audio/stem nguồn")
    report = progress or (lambda _message: None)
    result = render_longform_plan(
        base_options,
        plan_dubbing_segments(segments),
        client,
        profiles=profiles,
        cast_map=cast_map,
        gap_ms=0,
        export_mp3=export_mp3,
        export_stems=export_stems,
        progress=report,
        resume_project_dir=resume_project_dir,
        stop_event=stop_event,
        smart_fit=True,
        fit_policy=policy,
    )
    quality = build_dubbing_quality_report(
        segments,
        measurements=result.fit_measurements,
        policy=policy,
    )
    quality_path = result.project_dir / "dubbing_quality_report.json"
    write_json_atomic(
        quality_path,
        {
            "schema_version": 1,
            **quality.to_dict(),
            "policy": asdict(policy),
        },
    )
    mixed_audio_path: Path | None = None
    video_path: Path | None = None
    warnings = list(result.warnings)
    if source_video is not None or (source_audio is not None and normalized_mode != MIX_REPLACE):
        report("Đang trộn audio nguồn và đồng bộ video...")
        mixed_audio_path, video_path, media_warnings = _mix_and_mux(
            result,
            source_video=source_video,
            source_audio=source_audio,
            mix_mode=normalized_mode,
            source_volume=source_volume,
            dub_volume=dub_volume,
            stop_event=stop_event,
        )
        warnings.extend(media_warnings)

    updated = replace(
        result,
        quality_report_path=quality_path,
        mixed_audio_path=mixed_audio_path,
        video_path=video_path,
        warnings=tuple(warnings),
    )
    manifest = read_json(result.manifest_path)
    payload = dict(manifest) if isinstance(manifest, dict) else {}
    files = dict(payload.get("files") or {})
    files.update(
        {
            "quality_report": str(quality_path),
            "mixed_audio": str(mixed_audio_path) if mixed_audio_path else None,
            "video": str(video_path) if video_path else None,
        }
    )
    payload.update(
        {
            "workflow": "dubbing",
            "segments": [asdict(segment) for segment in segments],
            "quality": quality.to_dict(),
            "mix": {
                "mode": normalized_mode,
                "source_video": str(source_video) if source_video else "",
                "source_audio": str(source_audio) if source_audio else "",
                "source_volume": _volume(source_volume),
                "dub_volume": _volume(dub_volume),
            },
            "files": files,
            "warnings": warnings,
        }
    )
    write_json_atomic(result.manifest_path, payload)
    return updated


def _mix_and_mux(
    result: LongformWorkspaceResult,
    *,
    source_video: Path | None,
    source_audio: Path | None,
    mix_mode: str,
    source_volume: float,
    dub_volume: float,
    stop_event: threading.Event | None,
) -> tuple[Path | None, Path | None, tuple[str, ...]]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(ffmpeg_missing_message("mix and mux dubbed media"))
    warnings: list[str] = []
    resolved_source = Path(source_audio).expanduser() if source_audio is not None else None
    if resolved_source is None and source_video is not None and _has_audio_stream(source_video):
        resolved_source = Path(source_video)
    effective_mode = mix_mode
    if effective_mode != MIX_REPLACE and resolved_source is None:
        effective_mode = MIX_REPLACE
        warnings.append("Video nguồn không có audio; đã chuyển sang chế độ thay voice.")

    mixed_audio: Path | None = None
    if effective_mode != MIX_REPLACE and resolved_source is not None:
        mixed_audio = result.project_dir / "mixed_audio.wav"
        _run_ffmpeg(
            _audio_mix_command(
                ffmpeg,
                resolved_source,
                result.wav_path,
                mixed_audio,
                mode=effective_mode,
                source_volume=source_volume,
                dub_volume=dub_volume,
            ),
            _run_command,
            stop_event=stop_event,
        )

    if source_video is None:
        return mixed_audio, None, tuple(warnings)
    final_video = result.project_dir / "dubbed_video.mp4"
    audio_track = mixed_audio or result.wav_path
    video_duration = _media_duration_seconds(Path(source_video))
    _run_ffmpeg(
        _video_mux_command(
            ffmpeg,
            Path(source_video),
            audio_track,
            result.srt_path,
            final_video,
            dub_volume=dub_volume if mixed_audio is None else 1.0,
            video_duration=video_duration,
        ),
        _run_command,
        stop_event=stop_event,
    )
    return mixed_audio, final_video, tuple(warnings)


def _audio_mix_command(
    ffmpeg: str,
    source: Path,
    dub: Path,
    output: Path,
    *,
    mode: str,
    source_volume: float,
    dub_volume: float,
) -> list[str]:
    source_filter = f"[0:a]volume={_volume(source_volume):.3f}[source]"
    if mode == MIX_DUCK:
        dub_filter = f"[1:a]volume={_volume(dub_volume):.3f},asplit=2[dub_side][dub_mix]"
        mix_filter = (
            "[source][dub_side]sidechaincompress="
            "threshold=0.025:ratio=8:attack=20:release=300[ducked];"
            "[ducked][dub_mix]amix=inputs=2:duration=longest:normalize=0[mix]"
        )
    else:
        dub_filter = f"[1:a]volume={_volume(dub_volume):.3f}[dub]"
        mix_filter = "[source][dub]amix=inputs=2:duration=longest:normalize=0[mix]"
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-i",
        str(dub),
        "-filter_complex",
        f"{source_filter};{dub_filter};{mix_filter}",
        "-map",
        "[mix]",
        "-ar",
        "24000",
        "-ac",
        "1",
        str(output),
    ]


def _video_mux_command(
    ffmpeg: str,
    video: Path,
    audio: Path,
    subtitles: Path,
    output: Path,
    *,
    dub_volume: float,
    video_duration: float | None = None,
) -> list[str]:
    audio_filter = f"[1:a]volume={_volume(dub_volume):.3f},apad"
    if video_duration is not None:
        audio_filter += f",atrim=duration={video_duration:.3f}"
    audio_filter += "[dub]"
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-i",
        str(subtitles),
        "-filter_complex",
        audio_filter,
        "-map",
        "0:v:0",
        "-map",
        "[dub]",
        "-map",
        "2:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-c:s",
        "mov_text",
        "-map_metadata",
        "0",
    ]
    if video_duration is not None:
        command.extend(("-t", f"{video_duration:.3f}"))
    else:
        command.append("-shortest")
    command.append(str(output))
    return command


def _has_audio_stream(path: Path) -> bool:
    ffprobe = find_ffprobe()
    if not ffprobe:
        return False
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and completed.stdout.strip() == "audio"


def _media_duration_seconds(path: Path) -> float | None:
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        duration = float(completed.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return duration if completed.returncode == 0 and duration > 0 else None


def _validate_optional_file(path: Path | None, label: str) -> None:
    if path is not None and not Path(path).expanduser().is_file():
        raise ValueError(f"Không tìm thấy {label}: {path}")


def _volume(value: float) -> float:
    return max(0.0, min(2.0, float(value)))
