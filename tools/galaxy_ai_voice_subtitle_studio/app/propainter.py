from __future__ import annotations

import os
import shutil
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
FAST_CHUNK_SECONDS = 30.0
DEFAULT_OVERLAP_SECONDS = 1.0
QUALITY_AI_PROFILE = "quality"
FAST_AI_PROFILE = "fast"
AI_PROFILES = (QUALITY_AI_PROFILE, FAST_AI_PROFILE)
MIN_RAFT_PROCESSING_DIMENSION = 128


@dataclass(frozen=True)
class ProPainterTuning:
    subvideo_length: int
    neighbor_length: int
    ref_stride: int
    use_fp16: bool


@dataclass(frozen=True)
class InpaintingCropPlan:
    profile: str
    video_width: int
    video_height: int
    region_x: int
    region_y: int
    region_width: int
    region_height: int
    crop_x: int
    crop_y: int
    crop_width: int
    crop_height: int
    processing_width: int
    processing_height: int
    mask_x: int
    mask_y: int
    mask_width: int
    mask_height: int

@dataclass(frozen=True)
class ProPainterRuntime:
    repo_dir: Path
    python_executable: Path
    inference_script: Path


@dataclass
class ProPainterSession:
    runtime: ProPainterRuntime
    selected_device: str
    resolved_device: str
    gpu_memory_gb: float | None
    profile: str


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


def prepare_propainter_session(
    processing_device: str,
    *,
    profile: str,
) -> ProPainterSession:
    runtime = resolve_propainter_runtime()
    selected_device = normalize_processing_device(processing_device)
    resolved_device = resolve_propainter_device(runtime, selected_device)
    gpu_memory_gb = (
        propainter_cuda_memory_gb(runtime)
        if resolved_device == CUDA_DEVICE
        else None
    )
    return ProPainterSession(
        runtime=runtime,
        selected_device=selected_device,
        resolved_device=resolved_device,
        gpu_memory_gb=gpu_memory_gb,
        profile=_normalize_profile(profile),
    )


def build_propainter_command(
    runtime: ProPainterRuntime,
    video_path: Path,
    mask_path: Path,
    output_root: Path,
    processing_device: str,
    *,
    gpu_memory_gb: float | None = None,
    profile: str = QUALITY_AI_PROFILE,
    resize_ratio: float = 1.0,
) -> list[str]:
    device = normalize_processing_device(processing_device)
    tuning = propainter_tuning(device, gpu_memory_gb=gpu_memory_gb, profile=profile)
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
        str(tuning.subvideo_length),
        "--neighbor_length",
        str(tuning.neighbor_length),
        "--ref_stride",
        str(tuning.ref_stride),
    ]
    if tuning.use_fp16:
        command.append("--fp16")
    if resize_ratio < 1.0:
        command.extend(("--resize_ratio", f"{max(0.25, resize_ratio):.2f}"))
    return command


def propainter_tuning(
    processing_device: str,
    *,
    gpu_memory_gb: float | None,
    profile: str,
) -> ProPainterTuning:
    normalized_profile = _normalize_profile(profile)
    device = normalize_processing_device(processing_device)
    if device != CUDA_DEVICE:
        if normalized_profile == FAST_AI_PROFILE:
            return ProPainterTuning(30, 6, 15, False)
        return ProPainterTuning(24, 8, 12, False)

    memory = max(0.0, float(gpu_memory_gb or 0.0))
    if normalized_profile == FAST_AI_PROFILE:
        if memory >= 20.0:
            subvideo_length = 50
        elif memory >= 11.0:
            subvideo_length = 40
        elif memory >= 7.0:
            subvideo_length = 30
        else:
            return ProPainterTuning(24, 6, 12, True)
        return ProPainterTuning(subvideo_length, 6, 15, True)

    if memory >= 20.0:
        subvideo_length = 50
    elif memory >= 15.0:
        subvideo_length = 36
    elif memory >= 11.0:
        subvideo_length = 24
    elif memory >= 7.0:
        return ProPainterTuning(20, 6, 10, True)
    else:
        return ProPainterTuning(16, 6, 8, True)
    return ProPainterTuning(subvideo_length, 8, 12, True)


def recommended_chunk_seconds(session: ProPainterSession) -> float:
    if session.resolved_device != CUDA_DEVICE:
        return 15.0 if session.profile == FAST_AI_PROFILE else DEFAULT_CHUNK_SECONDS

    memory = max(0.0, float(session.gpu_memory_gb or 0.0))
    if session.profile == FAST_AI_PROFILE:
        if memory >= 11.0:
            return FAST_CHUNK_SECONDS
        if memory >= 7.0:
            return DEFAULT_CHUNK_SECONDS
        return 15.0
    if memory >= 11.0:
        return DEFAULT_CHUNK_SECONDS
    if memory >= 7.0:
        return 15.0
    return 12.0


def recommended_processing_size(session: ProPainterSession) -> tuple[int, int]:
    memory = max(0.0, float(session.gpu_memory_gb or 0.0))
    if session.profile == FAST_AI_PROFILE:
        if session.resolved_device != CUDA_DEVICE or memory < 7.0:
            return 480, 240
        if memory < 11.0:
            return 576, 288
        return 640, 320

    if session.resolved_device != CUDA_DEVICE or memory < 7.0:
        return 640, 360
    if memory < 11.0:
        return 800, 450
    return 960, 540


def propainter_environment(
    resolved_device: str,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(base_environment or os.environ)
    environment["CUDA_VISIBLE_DEVICES"] = "0" if resolved_device == CUDA_DEVICE else ""
    return environment


def plan_inpainting_crop(
    *,
    video_size: tuple[int, int],
    region: Region,
    profile: str,
    maximum_processing_size: tuple[int, int] | None = None,
) -> InpaintingCropPlan:
    normalized_profile = _normalize_profile(profile)
    video_width, video_height = video_size
    if video_width < 8 or video_height < 8:
        raise ValueError("The video is too small for AI inpainting.")

    region_x, region_y, region_width, region_height = _pixel_region(region, video_size)
    if normalized_profile == FAST_AI_PROFILE:
        horizontal_padding = max(8, round(region_width * 0.02))
        vertical_padding = max(16, round(region_height * 0.40))
        profile_maximum_size = (640, 320)
    else:
        horizontal_padding = max(16, round(region_width * 0.05))
        vertical_padding = max(24, round(region_height * 0.75))
        profile_maximum_size = (960, 540)

    maximum_size = maximum_processing_size or profile_maximum_size
    if maximum_size[0] < 8 or maximum_size[1] < 8:
        raise ValueError("The maximum AI processing size must be at least 8x8.")

    crop_x = max(0, region_x - horizontal_padding)
    crop_y = max(0, region_y - vertical_padding)
    crop_right = min(video_width, region_x + region_width + horizontal_padding)
    crop_bottom = min(video_height, region_y + region_height + vertical_padding)
    crop_width = crop_right - crop_x
    crop_height = crop_bottom - crop_y
    processing_width, processing_height = _fit_processing_size(
        (crop_width, crop_height),
        maximum_size,
    )

    scale_x = processing_width / crop_width
    scale_y = processing_height / crop_height
    mask_x = max(0, round((region_x - crop_x) * scale_x))
    mask_y = max(0, round((region_y - crop_y) * scale_y))
    mask_right = min(
        processing_width,
        max(mask_x + 1, round((region_x + region_width - crop_x) * scale_x)),
    )
    mask_bottom = min(
        processing_height,
        max(mask_y + 1, round((region_y + region_height - crop_y) * scale_y)),
    )

    return InpaintingCropPlan(
        profile=normalized_profile,
        video_width=video_width,
        video_height=video_height,
        region_x=region_x,
        region_y=region_y,
        region_width=region_width,
        region_height=region_height,
        crop_x=crop_x,
        crop_y=crop_y,
        crop_width=crop_width,
        crop_height=crop_height,
        processing_width=processing_width,
        processing_height=processing_height,
        mask_x=mask_x,
        mask_y=mask_y,
        mask_width=mask_right - mask_x,
        mask_height=mask_bottom - mask_y,
    )


def build_inpainting_mask_command(
    ffmpeg: str,
    output_path: Path,
    plan: InpaintingCropPlan,
) -> list[str]:
    return _build_pixel_mask_image_command(
        ffmpeg,
        output_path,
        image_size=(plan.processing_width, plan.processing_height),
        pixel_region=(plan.mask_x, plan.mask_y, plan.mask_width, plan.mask_height),
    )


def _build_pixel_mask_image_command(
    ffmpeg: str,
    output_path: Path,
    *,
    image_size: tuple[int, int],
    pixel_region: Region,
) -> list[str]:
    image_width, image_height = image_size
    x, y, width, height = pixel_region
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={image_width}x{image_height}",
        "-vf",
        f"drawbox=x={x}:y={y}:w={width}:h={height}:color=white:t=fill",
        "-frames:v",
        "1",
        str(output_path),
    ]


def build_inpainting_input_command(
    ffmpeg: str,
    source_path: Path,
    output_path: Path,
    plan: InpaintingCropPlan,
) -> list[str]:
    video_filter = (
        f"crop={plan.crop_width}:{plan.crop_height}:{plan.crop_x}:{plan.crop_y},"
        f"scale={plan.processing_width}:{plan.processing_height}:flags=lanczos,setsar=1"
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


def build_inpainting_merge_command(
    ffmpeg: str,
    source_path: Path,
    inpainted_crop: Path,
    output_path: Path,
    plan: InpaintingCropPlan,
    *,
    duration_seconds: float,
) -> list[str]:
    relative_x = plan.region_x - plan.crop_x
    relative_y = plan.region_y - plan.crop_y
    clean_filter = (
        f"[1:v:0]setpts=PTS-STARTPTS,scale={plan.crop_width}:{plan.crop_height}:flags=lanczos,"
        f"crop={plan.region_width}:{plan.region_height}:{relative_x}:{relative_y},"
        "setsar=1[clean];"
        "[0:v:0]setpts=PTS-STARTPTS[base];"
    )
    feather = min(4, max(0, (min(plan.region_width, plan.region_height) - 1) // 2))
    if feather:
        inner_width = max(1, plan.region_width - feather * 2)
        inner_height = max(1, plan.region_height - feather * 2)
        blend_filter = (
            f"color=c=black:s={plan.region_width}x{plan.region_height},format=gray,"
            f"drawbox=x={feather}:y={feather}:w={inner_width}:h={inner_height}:"
            f"color=white:t=fill,boxblur=luma_radius={feather}:luma_power=1[alpha];"
            "[clean][alpha]alphamerge=shortest=1[clean_alpha];"
        )
        overlay_input = "clean_alpha"
    else:
        blend_filter = ""
        overlay_input = "clean"
    filter_graph = (
        clean_filter
        + blend_filter
        + f"[base][{overlay_input}]overlay=x={plan.region_x}:y={plan.region_y}:"
        "eof_action=repeat:repeatlast=1[video]"
    )
    preset = "fast" if plan.profile == FAST_AI_PROFILE else "medium"
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-i",
        str(inpainted_crop),
        "-filter_complex",
        filter_graph,
        "-map",
        "[video]",
        "-map",
        "0:a?",
        "-map_metadata",
        "0",
        "-sn",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-af",
        "aresample=async=1:first_pts=0",
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


def run_propainter(
    video_path: Path,
    mask_path: Path,
    output_root: Path,
    processing_device: str,
    progress: ProgressCallback,
    *,
    profile: str = QUALITY_AI_PROFILE,
    session: ProPainterSession | None = None,
) -> Path:
    managed_media_processes.ensure_running()
    prepared = session or prepare_propainter_session(
        processing_device,
        profile=profile,
    )
    runtime = prepared.runtime
    selected_device = prepared.selected_device
    resolved_device = prepared.resolved_device
    profile = prepared.profile
    if selected_device == AUTO_DEVICE and resolved_device == CPU_DEVICE:
        progress("ProPainter CUDA runtime is unavailable. Falling back to CPU...")
    output_root.mkdir(parents=True, exist_ok=True)
    gpu_memory_gb = prepared.gpu_memory_gb
    if resolved_device == CUDA_DEVICE and gpu_memory_gb is not None:
        hardware = (
            f"CUDA ({gpu_memory_gb:.1f} GB available VRAM)"
            if gpu_memory_gb > 0
            else "CUDA (low-memory profile)"
        )
    else:
        hardware = resolved_device.upper()
    attempt_memory_gb = gpu_memory_gb
    attempt_resize_ratio = 1.0
    oom_retry_attempted = False
    while True:
        tuning = propainter_tuning(
            resolved_device,
            gpu_memory_gb=attempt_memory_gb,
            profile=profile,
        )
        command = build_propainter_command(
            runtime,
            video_path,
            mask_path,
            output_root,
            resolved_device,
            gpu_memory_gb=attempt_memory_gb,
            profile=profile,
            resize_ratio=attempt_resize_ratio,
        )
        precision = "FP16" if tuning.use_fp16 else "FP32"
        progress(
            f"Starting ProPainter {profile} on {hardware}: {precision}, "
            f"subvideo {tuning.subvideo_length}, neighbors {tuning.neighbor_length}..."
        )
        return_code, recent_output = _run_propainter_process(
            command,
            runtime,
            resolved_device,
            progress,
        )
        if return_code == 0:
            break

        detail = "\n".join(recent_output) or f"ProPainter exited with code {return_code}."
        can_retry = (
            resolved_device == CUDA_DEVICE
            and not oom_retry_attempted
            and _is_cuda_out_of_memory(detail)
        )
        if not can_retry:
            raise RuntimeError(detail)

        progress(
            "CUDA ran out of memory. Retrying this chunk with the smallest safe AI context..."
        )
        attempt_memory_gb = 0.0
        attempt_resize_ratio = 0.75
        oom_retry_attempted = True
        prepared.gpu_memory_gb = 0.0
        shutil.rmtree(output_root / video_path.stem, ignore_errors=True)

    result_path = output_root / video_path.stem / "inpaint_out.mp4"
    if not result_path.is_file() or result_path.stat().st_size == 0:
        raise RuntimeError(f"ProPainter did not create its output video: {result_path}")
    return result_path


def _run_propainter_process(
    command: list[str],
    runtime: ProPainterRuntime,
    resolved_device: str,
    progress: ProgressCallback,
) -> tuple[int, deque[str]]:
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
    return return_code, recent_output


def _is_cuda_out_of_memory(detail: str) -> bool:
    normalized = detail.lower()
    return any(
        marker in normalized
        for marker in (
            "cuda out of memory",
            "outofmemoryerror",
            "cublas_status_alloc_failed",
        )
    )


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


def propainter_cuda_memory_gb(runtime: ProPainterRuntime) -> float | None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    code = (
        "import torch; "
        "free, total = torch.cuda.mem_get_info() if torch.cuda.is_available() else (0, 0); "
        "print(max(0, free - 512 * 1024 ** 2) / (1024 ** 3))"
    )
    try:
        completed = subprocess.run(
            [str(runtime.python_executable), "-c", code],
            cwd=runtime.repo_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            creationflags=creationflags,
        )
        memory = float(completed.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or memory <= 0:
        return None
    return memory


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
    x = max(0, min(video_width - 1, round(video_width * x_percent / 100)))
    y = max(0, min(video_height - 1, round(video_height * y_percent / 100)))
    right = max(x + 1, min(video_width, round(video_width * (x_percent + width_percent) / 100)))
    bottom = max(y + 1, min(video_height, round(video_height * (y_percent + height_percent) / 100)))
    return x, y, right - x, bottom - y


def _fit_processing_size(
    source_size: tuple[int, int],
    maximum_size: tuple[int, int],
) -> tuple[int, int]:
    source_width, source_height = source_size
    maximum_width, maximum_height = maximum_size
    maximum_width = max(
        MIN_RAFT_PROCESSING_DIMENSION,
        maximum_width // 8 * 8,
    )
    maximum_height = max(
        MIN_RAFT_PROCESSING_DIMENSION,
        maximum_height // 8 * 8,
    )
    scale = min(
        1.0,
        maximum_width / source_width,
        maximum_height / source_height,
    )
    scaled_width = source_width * scale
    scaled_height = source_height * scale

    shortest_dimension = min(scaled_width, scaled_height)
    if shortest_dimension < MIN_RAFT_PROCESSING_DIMENSION:
        upscale = min(
            maximum_width / scaled_width,
            maximum_height / scaled_height,
            MIN_RAFT_PROCESSING_DIMENSION / shortest_dimension,
        )
        scaled_width *= upscale
        scaled_height *= upscale

    width = max(
        MIN_RAFT_PROCESSING_DIMENSION,
        min(maximum_width, int(scaled_width) // 8 * 8),
    )
    height = max(
        MIN_RAFT_PROCESSING_DIMENSION,
        min(maximum_height, int(scaled_height) // 8 * 8),
    )
    return width, height


def _normalize_profile(profile: str) -> str:
    normalized = str(profile).strip().lower()
    if normalized not in AI_PROFILES:
        raise ValueError(f"Unknown ProPainter profile: {profile}")
    return normalized


def _seconds(value: float) -> str:
    return f"{max(0.0, value):.3f}"
