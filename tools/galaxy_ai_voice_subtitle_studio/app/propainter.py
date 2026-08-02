from __future__ import annotations

import os
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .compute import AUTO_DEVICE, CPU_DEVICE, CUDA_DEVICE, normalize_processing_device, resolve_torch_device
from .processes import managed_media_processes

ProgressCallback = Callable[[str], None]
Region = tuple[int, int, int, int]
DEFAULT_CHUNK_SECONDS = 20.0
DEFAULT_OVERLAP_SECONDS = 1.0

@dataclass(frozen=True)
class ProPainterRuntime:
    repo_dir: Path
    python_executable: Path
    inference_script: Path


@dataclass(frozen=True)
class VideoChunk:
    source_start: float
    source_duration: float
    trim_start: float
    trim_duration: float


def default_propainter_dir() -> Path:
    configured = os.environ.get("GALAXY_PROPAINTER_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "GalaxyAIStudio" / "models" / "ProPainter"


def resolve_propainter_runtime(repo_dir: Path | None = None) -> ProPainterRuntime:
    repository = Path(repo_dir) if repo_dir is not None else default_propainter_dir()
    configured_python = os.environ.get("GALAXY_PROPAINTER_PYTHON", "").strip()
    python_executable = (
        Path(configured_python).expanduser()
        if configured_python
        else repository / ".venv" / "Scripts" / "python.exe"
    )
    inference_script = repository / "inference_propainter.py"
    missing = [
        str(path)
        for path in (repository, python_executable, inference_script)
        if not path.exists()
    ]
    if missing:
        raise RuntimeError(
            "ProPainter is not installed completely. Run install_propainter.ps1 first. "
            f"Missing: {', '.join(missing)}"
        )
    return ProPainterRuntime(repository, python_executable, inference_script)


def build_propainter_command(
    runtime: ProPainterRuntime,
    video_path: Path,
    mask_path: Path,
    output_root: Path,
    processing_device: str,
) -> list[str]:
    device = normalize_processing_device(processing_device)
    command = [
        str(runtime.python_executable),
        str(runtime.inference_script),
        "--video",
        str(video_path),
        "--mask",
        str(mask_path),
        "--output",
        str(output_root),
        "--subvideo_length",
        "50",
        "--neighbor_length",
        "8",
        "--ref_stride",
        "12",
    ]
    if device == CUDA_DEVICE:
        command.append("--fp16")
    return command


def propainter_environment(
    resolved_device: str,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(base_environment or os.environ)
    environment["CUDA_VISIBLE_DEVICES"] = "0" if resolved_device == CUDA_DEVICE else ""
    return environment


def build_mask_image_command(
    ffmpeg: str,
    output_path: Path,
    *,
    video_size: tuple[int, int],
    region: Region,
) -> list[str]:
    video_width, video_height = video_size
    x, y, width, height = _pixel_region(region, video_size)
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={video_width}x{video_height}",
        "-vf",
        f"drawbox=x={x}:y={y}:w={width}:h={height}:color=white:t=fill",
        "-frames:v",
        "1",
        str(output_path),
    ]


def build_propainter_input_command(ffmpeg: str, source_path: Path, output_path: Path) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-fps_mode",
        "cfr",
        str(output_path),
    ]


def plan_video_chunks(
    duration_seconds: float,
    *,
    chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
) -> list[VideoChunk]:
    if duration_seconds <= 0:
        raise ValueError("Video duration must be positive.")
    if chunk_seconds <= 0:
        raise ValueError("ProPainter chunk length must be positive.")
    if overlap_seconds < 0 or overlap_seconds >= chunk_seconds / 2:
        raise ValueError("ProPainter overlap must be non-negative and shorter than half a chunk.")

    chunks: list[VideoChunk] = []
    retained_start = 0.0
    while retained_start < duration_seconds:
        retained_end = min(duration_seconds, retained_start + chunk_seconds)
        source_start = max(0.0, retained_start - overlap_seconds)
        source_end = min(duration_seconds, retained_end + overlap_seconds)
        chunks.append(
            VideoChunk(
                source_start=source_start,
                source_duration=source_end - source_start,
                trim_start=retained_start - source_start,
                trim_duration=retained_end - retained_start,
            )
        )
        retained_start = retained_end
    return chunks


def build_chunk_extract_command(
    ffmpeg: str,
    source_path: Path,
    output_path: Path,
    chunk: VideoChunk,
) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        _seconds(chunk.source_start),
        "-i",
        str(source_path),
        "-t",
        _seconds(chunk.source_duration),
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-fps_mode",
        "cfr",
        str(output_path),
    ]


def build_chunk_trim_command(
    ffmpeg: str,
    source_path: Path,
    output_path: Path,
    chunk: VideoChunk,
) -> list[str]:
    video_filter = (
        f"trim=start={_seconds(chunk.trim_start)}:duration={_seconds(chunk.trim_duration)},"
        "setpts=PTS-STARTPTS"
    )
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-fps_mode",
        "cfr",
        str(output_path),
    ]


def write_concat_file(video_paths: list[Path], concat_path: Path) -> None:
    if not video_paths:
        raise ValueError("At least one video chunk is required.")
    lines: list[str] = []
    for video_path in video_paths:
        try:
            relative_path = video_path.relative_to(concat_path.parent)
        except ValueError as error:
            raise ValueError("Concat chunks must be inside the concat file folder.") from error
        normalized = relative_path.as_posix()
        if "'" in normalized:
            raise ValueError("Generated chunk names cannot contain apostrophes.")
        lines.append(f"file '{normalized}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_concat_command(ffmpeg: str, concat_path: Path, output_path: Path) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "copy",
        str(output_path),
    ]


def build_remux_audio_command(
    ffmpeg: str,
    inpainted_video: Path,
    source_video: Path,
    output_path: Path,
    duration_seconds: float,
) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(inpainted_video),
        "-i",
        str(source_video),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-map_metadata",
        "1",
        "-sn",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        _seconds(duration_seconds),
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def run_propainter(
    video_path: Path,
    mask_path: Path,
    output_root: Path,
    processing_device: str,
    progress: ProgressCallback,
) -> Path:
    managed_media_processes.ensure_running()
    runtime = resolve_propainter_runtime()
    selected_device = normalize_processing_device(processing_device)
    resolved_device = resolve_propainter_device(runtime, selected_device)
    if selected_device == AUTO_DEVICE and resolved_device == CPU_DEVICE:
        progress("ProPainter CUDA runtime is unavailable. Falling back to CPU...")
    output_root.mkdir(parents=True, exist_ok=True)
    command = build_propainter_command(
        runtime,
        video_path,
        mask_path,
        output_root,
        resolved_device,
    )
    progress(f"Starting ProPainter on {resolved_device.upper()}...")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=runtime.repo_dir,
        env=propainter_environment(resolved_device),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    managed_media_processes.add(process)
    recent_output: deque[str] = deque(maxlen=20)
    try:
        if process.stdout is not None:
            for line in process.stdout:
                message = line.strip()
                if message:
                    recent_output.append(message)
                    progress(message)
        return_code = process.wait()
    finally:
        managed_media_processes.discard(process)
    if return_code != 0:
        detail = "\n".join(recent_output) or f"ProPainter exited with code {return_code}."
        raise RuntimeError(detail)

    result_path = output_root / video_path.stem / "inpaint_out.mp4"
    if not result_path.is_file() or result_path.stat().st_size == 0:
        raise RuntimeError(f"ProPainter did not create its output video: {result_path}")
    return result_path


def propainter_cuda_available(runtime: ProPainterRuntime) -> bool:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [
                str(runtime.python_executable),
                "-c",
                "import torch; print('1' if torch.cuda.is_available() and "
                "torch.backends.cudnn.is_available() else '0')",
            ],
            cwd=runtime.repo_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and completed.stdout.strip() == "1"


def resolve_propainter_device(
    runtime: ProPainterRuntime,
    processing_device: str,
    *,
    nvidia_available: bool | None = None,
    cuda_available: bool | None = None,
) -> str:
    selected_device = normalize_processing_device(processing_device)
    resolved_device = resolve_torch_device(
        selected_device,
        nvidia_available=nvidia_available,
    )
    if resolved_device != CUDA_DEVICE:
        return resolved_device

    runtime_has_cuda = (
        propainter_cuda_available(runtime)
        if cuda_available is None
        else cuda_available
    )
    if runtime_has_cuda:
        return CUDA_DEVICE
    if selected_device == CUDA_DEVICE:
        raise RuntimeError(
            "The installed ProPainter PyTorch runtime cannot use CUDA with cuDNN. "
            "Re-run install_propainter.ps1 with -Device cuda or choose CPU."
        )
    return CPU_DEVICE


def _pixel_region(region: Region, video_size: tuple[int, int]) -> Region:
    x_percent, y_percent, width_percent, height_percent = region
    video_width, video_height = video_size
    x = round(video_width * x_percent / 100)
    y = round(video_height * y_percent / 100)
    width = round(video_width * width_percent / 100)
    height = round(video_height * height_percent / 100)
    return x, y, width, height


def _seconds(value: float) -> str:
    return f"{max(0.0, value):.3f}"
