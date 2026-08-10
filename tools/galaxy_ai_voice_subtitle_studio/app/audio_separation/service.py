from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from ..common.cache import read_json, write_json_atomic
from ..common.compute import detect_nvidia_hardware
from ..common.ffmpeg import ffmpeg_missing_message, find_ffmpeg
from ..common.paths import repository_root, unique_project_dir
from ..common.processes import managed_media_processes, terminate_process_tree

MDX_METHOD = "mdx"
VR_METHOD = "vr"
DEMUCS_METHOD = "demucs"
AUDIO_PROCESS_METHODS = (MDX_METHOD, VR_METHOD, DEMUCS_METHOD)
AUDIO_PROCESS_METHOD_LABELS = {
    MDX_METHOD: "MDX-Net",
    VR_METHOD: "VR Architecture",
    DEMUCS_METHOD: "Demucs",
}
AUDIO_PROCESS_METHOD_CODES = {
    label: code for code, label in AUDIO_PROCESS_METHOD_LABELS.items()
}

AUTO_AUDIO_DEVICE = "auto"
CPU_AUDIO_DEVICE = "cpu"
DIRECTML_AUDIO_DEVICE = "directml"
CUDA_AUDIO_DEVICE = "cuda"
AUDIO_PROCESSING_DEVICES = (
    AUTO_AUDIO_DEVICE,
    CPU_AUDIO_DEVICE,
    DIRECTML_AUDIO_DEVICE,
    CUDA_AUDIO_DEVICE,
)
AUDIO_PROCESSING_DEVICE_LABELS = {
    AUTO_AUDIO_DEVICE: "Tự động",
    CPU_AUDIO_DEVICE: "CPU",
    DIRECTML_AUDIO_DEVICE: "Intel / AMD DirectML",
    CUDA_AUDIO_DEVICE: "NVIDIA CUDA",
}
AUDIO_PROCESSING_DEVICE_CODES = {
    label: code for code, label in AUDIO_PROCESSING_DEVICE_LABELS.items()
}

AUDIO_OUTPUT_FORMATS = ("WAV", "FLAC", "MP3")
AUDIO_SAVED_SETTINGS = (
    "Default",
    "Vocal extraction",
    "Instrumental / Karaoke",
    "Denoise",
)
AUDIO_PRESET_FIELDS = {
    "method",
    "model_filename",
    "output_format",
    "segment_size",
    "overlap",
    "processing_device",
    "gpu_conversion",
    "vocals_only",
    "instrumental_only",
    "sample_mode",
}

VIDEO_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".flv",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
    ".wmv",
}

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class UVRModel:
    method: str
    label: str
    filename: str
    model_dir: Path

    @property
    def path(self) -> Path:
        return self.model_dir / self.filename


@dataclass(frozen=True)
class AudioSeparatorRuntime:
    python_path: Path


@dataclass(frozen=True)
class AudioSeparationOptions:
    input_path: Path
    output_dir: Path
    project_name: str = ""
    method: str = MDX_METHOD
    model_filename: str = "Kim_Vocal_2.onnx"
    output_format: str = "WAV"
    segment_size: str = "256"
    overlap: str = "Default"
    processing_device: str = AUTO_AUDIO_DEVICE
    vocals_only: bool = False
    instrumental_only: bool = False
    sample_mode: bool = False


@dataclass(frozen=True)
class AudioSeparationResult:
    project_dir: Path
    output_paths: tuple[Path, ...]
    manifest_path: Path
    warnings: tuple[str, ...]


def load_audio_presets(path: Path) -> dict[str, dict[str, object]]:
    payload = read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("presets"), dict):
        return {}
    presets: dict[str, dict[str, object]] = {}
    for name, settings in payload["presets"].items():
        if not isinstance(name, str) or not name.strip() or not isinstance(settings, dict):
            continue
        cleaned = {
            key: value
            for key, value in settings.items()
            if key in AUDIO_PRESET_FIELDS and isinstance(value, (str, bool))
        }
        if cleaned:
            presets[name.strip()] = cleaned
    return presets


def save_audio_presets(path: Path, presets: dict[str, dict[str, object]]) -> None:
    write_json_atomic(path, {"version": 1, "presets": presets})


def default_uvr_root() -> Path:
    configured = os.environ.get("GALAXY_UVR_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return repository_root() / "ultimatevocalremover"


def default_audio_separator_runtime() -> AudioSeparatorRuntime:
    configured = os.environ.get("GALAXY_AUDIO_SEPARATOR_PYTHON", "").strip()
    if configured:
        return AudioSeparatorRuntime(Path(configured).expanduser())
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return AudioSeparatorRuntime(
        base / "GalaxyAIStudio" / "models" / "AudioSeparator" / ".venv" / "Scripts" / "python.exe"
    )


def discover_uvr_models(uvr_root: Path | None = None) -> tuple[UVRModel, ...]:
    root = Path(uvr_root or default_uvr_root()).expanduser()
    definitions: tuple[tuple[str, Path, str], ...] = (
        (MDX_METHOD, root / "models" / "MDX_Net_Models", "*.onnx"),
        (VR_METHOD, root / "models" / "VR_Models", "*.pth"),
    )
    models: list[UVRModel] = []
    for method, directory, pattern in definitions:
        if directory.is_dir():
            models.extend(_models_from_paths(method, directory.glob(pattern)))

    demucs_root = root / "models" / "Demucs_Models"
    if demucs_root.is_dir():
        models.extend(_models_from_paths(DEMUCS_METHOD, demucs_root.rglob("*.yaml")))

    method_order = {method: index for index, method in enumerate(AUDIO_PROCESS_METHODS)}
    return tuple(
        sorted(models, key=lambda model: (method_order[model.method], model.label.casefold()))
    )


def _models_from_paths(method: str, paths: Iterable[Path]) -> list[UVRModel]:
    return [
        UVRModel(
            method=method,
            label=_model_label(path.name),
            filename=path.name,
            model_dir=path.parent,
        )
        for path in paths
        if path.is_file()
    ]


def _model_label(filename: str) -> str:
    known_labels = {
        "Kim_Vocal_2.onnx": "Kim Vocal 2",
        "UVR-MDX-NET-Inst_HQ_3.onnx": "UVR-MDX-NET Inst HQ 3",
        "UVR-MDX-NET-Inst_HQ_5.onnx": "UVR-MDX-NET Inst HQ 5",
        "1_HP-UVR.pth": "1 HP-UVR",
        "UVR-DeNoise-Lite.pth": "UVR DeNoise Lite",
        "htdemucs.yaml": "HTDemucs",
    }
    if filename in known_labels:
        return known_labels[filename]
    return Path(filename).stem.replace("_", " ").replace("-", " ")


def normalize_audio_method(value: str) -> str:
    normalized = str(value).strip().lower()
    return normalized if normalized in AUDIO_PROCESS_METHODS else MDX_METHOD


def audio_method_label(code: str) -> str:
    return AUDIO_PROCESS_METHOD_LABELS[normalize_audio_method(code)]


def audio_method_code(label_or_code: str) -> str:
    if label_or_code in AUDIO_PROCESS_METHOD_CODES:
        return AUDIO_PROCESS_METHOD_CODES[label_or_code]
    return normalize_audio_method(label_or_code)


def normalize_audio_device(value: str) -> str:
    normalized = str(value).strip().lower()
    return normalized if normalized in AUDIO_PROCESSING_DEVICES else AUTO_AUDIO_DEVICE


def audio_device_label(code: str) -> str:
    return AUDIO_PROCESSING_DEVICE_LABELS[normalize_audio_device(code)]


def audio_device_code(label_or_code: str) -> str:
    if label_or_code in AUDIO_PROCESSING_DEVICE_CODES:
        return AUDIO_PROCESSING_DEVICE_CODES[label_or_code]
    return normalize_audio_device(label_or_code)


def resolve_audio_device(
    selected_device: str,
    method: str,
    *,
    nvidia_available: bool | None = None,
    directml_available: bool | None = None,
) -> str:
    selected = normalize_audio_device(selected_device)
    normalized_method = normalize_audio_method(method)
    has_nvidia = detect_nvidia_hardware() if nvidia_available is None else nvidia_available
    has_directml = os.name == "nt" if directml_available is None else directml_available

    if selected == CPU_AUDIO_DEVICE:
        return CPU_AUDIO_DEVICE
    if selected == CUDA_AUDIO_DEVICE:
        if not has_nvidia:
            raise RuntimeError(
                "NVIDIA CUDA was selected, but no NVIDIA GPU was detected."
            )
        return CUDA_AUDIO_DEVICE
    if selected == DIRECTML_AUDIO_DEVICE:
        if normalized_method == DEMUCS_METHOD:
            raise RuntimeError(
                "Demucs does not support DirectML reliably. Choose Auto, CPU, or NVIDIA CUDA."
            )
        if not has_directml:
            raise RuntimeError("DirectML is only available on supported Windows GPUs.")
        return DIRECTML_AUDIO_DEVICE

    if has_nvidia:
        return CUDA_AUDIO_DEVICE
    if has_directml and normalized_method in {MDX_METHOD, VR_METHOD}:
        return DIRECTML_AUDIO_DEVICE
    return CPU_AUDIO_DEVICE


def audio_separator_runtime_ready(
    runtime: AudioSeparatorRuntime | None = None,
    processing_device: str | None = None,
    method: str | None = None,
) -> tuple[bool, str]:
    selected = runtime or default_audio_separator_runtime()
    if not selected.python_path.is_file():
        return False, f"Runtime chưa được cài: {selected.python_path}"
    probe = _runtime_probe(processing_device, method)
    try:
        completed = subprocess.run(
            [
                str(selected.python_path),
                "-c",
                probe,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"Không thể kiểm tra runtime: {error}"
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return False, detail or "audio-separator chưa được cài trong runtime."
    return True, "audio-separator đã sẵn sàng."


def _runtime_probe(processing_device: str | None, method: str | None) -> str:
    device = normalize_audio_device(processing_device or CPU_AUDIO_DEVICE)
    normalized_method = normalize_audio_method(method or MDX_METHOD)
    statements = ["import audio_separator"]
    if normalized_method == MDX_METHOD:
        statements.append("import onnxruntime as ort")
        provider = {
            DIRECTML_AUDIO_DEVICE: "DmlExecutionProvider",
            CUDA_AUDIO_DEVICE: "CUDAExecutionProvider",
            CPU_AUDIO_DEVICE: "CPUExecutionProvider",
        }.get(device, "CPUExecutionProvider")
        statements.append(
            f"assert '{provider}' in ort.get_available_providers(), "
            f"'Missing ONNX Runtime provider: {provider}'"
        )
    elif device == DIRECTML_AUDIO_DEVICE:
        statements.extend(("import torch_directml", "torch_directml.device()"))
    elif device == CUDA_AUDIO_DEVICE:
        statements.extend(("import torch", "assert torch.cuda.is_available(), 'CUDA is unavailable'"))
    else:
        statements.append("import torch")
    statements.append("print('ready')")
    return "; ".join(statements)


def build_audio_separator_command(
    runtime: AudioSeparatorRuntime,
    options: AudioSeparationOptions,
    model: UVRModel,
    project_dir: Path,
    input_path: Path,
    resolved_device: str,
) -> list[str]:
    if options.vocals_only and options.instrumental_only:
        raise ValueError("Vocals Only và Instrumental Only không thể cùng được chọn.")
    method = normalize_audio_method(options.method)
    if model.method != method:
        raise ValueError("The selected model does not match the process method.")
    output_format = options.output_format.strip().upper()
    if output_format not in AUDIO_OUTPUT_FORMATS:
        raise ValueError(f"Unsupported output format: {options.output_format}")

    command = [
        str(runtime.python_path),
        "-c",
        "from audio_separator.utils.cli import main; main()",
        "--model_filename",
        model.filename,
        "--model_file_dir",
        str(model.model_dir),
        "--output_dir",
        str(project_dir),
        "--output_format",
        output_format,
        "--output_bitrate",
        "320k",
        "--sample_rate",
        "44100",
        "--custom_output_names",
        json.dumps(_custom_output_names(options.input_path.stem), ensure_ascii=True),
    ]

    if resolved_device == DIRECTML_AUDIO_DEVICE:
        command.append("--use_directml")
    elif resolved_device == CUDA_AUDIO_DEVICE:
        command.append("--use_autocast")

    if options.vocals_only:
        command.extend(["--single_stem", "Vocals"])
    elif options.instrumental_only:
        command.extend(["--single_stem", "Instrumental"])

    segment_size = options.segment_size.strip()
    overlap = options.overlap.strip()
    if method == MDX_METHOD:
        if segment_size and segment_size.lower() != "default":
            command.extend(["--mdx_segment_size", str(int(segment_size))])
        if overlap and overlap.lower() != "default":
            command.extend(["--mdx_overlap", _normalized_float(overlap, 0.001, 0.999)])
    elif method == VR_METHOD:
        if segment_size and segment_size.lower() != "default":
            command.extend(["--vr_window_size", str(int(segment_size))])
        if overlap and overlap.lower() != "default":
            command.extend(["--vr_aggression", str(int(overlap))])
    elif method == DEMUCS_METHOD:
        if segment_size and segment_size.lower() != "default":
            command.extend(["--demucs_segment_size", str(int(segment_size))])
        if overlap and overlap.lower() != "default":
            command.extend(["--demucs_overlap", _normalized_float(overlap, 0.0, 0.99)])

    command.append(str(input_path))
    return command


def _normalized_float(value: str, minimum: float, maximum: float) -> str:
    parsed = float(value)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"Value must be between {minimum} and {maximum}: {value}")
    return f"{parsed:g}"


def _custom_output_names(source_stem: str) -> dict[str, str]:
    return {
        stem: f"{source_stem}_{stem.lower().replace(' ', '_')}"
        for stem in (
            "Vocals",
            "Instrumental",
            "Drums",
            "Bass",
            "Guitar",
            "Piano",
            "Other",
            "No Noise",
            "Noise",
        )
    }


def build_prepare_audio_command(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    *,
    sample_mode: bool,
) -> list[str]:
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
    ]
    if sample_mode:
        command.extend(["-t", "30"])
    command.append(str(output_path))
    return command


def separate_audio(
    options: AudioSeparationOptions,
    *,
    progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
    uvr_root: Path | None = None,
    runtime: AudioSeparatorRuntime | None = None,
    ffmpeg_path: str | None = None,
) -> AudioSeparationResult:
    report = progress or (lambda _message: None)
    cancellation = stop_event or threading.Event()
    input_path = Path(options.input_path).expanduser()
    if not input_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file đầu vào: {input_path}")

    models = discover_uvr_models(uvr_root)
    method = normalize_audio_method(options.method)
    model = next(
        (
            candidate
            for candidate in models
            if candidate.method == method and candidate.filename == options.model_filename
        ),
        None,
    )
    if model is None:
        raise FileNotFoundError(
            "Không tìm thấy model đã chọn trong thư mục Ultimate Vocal Remover: "
            f"{options.model_filename}"
        )

    selected_runtime = runtime or default_audio_separator_runtime()
    resolved_device = resolve_audio_device(options.processing_device, method)
    ready, runtime_message = audio_separator_runtime_ready(
        selected_runtime,
        resolved_device,
        method,
    )
    if not ready:
        raise RuntimeError(
            f"{runtime_message}\nChạy install_audio_separator.ps1 để cài engine tách âm thanh."
        )
    warnings: list[str] = []
    if (
        normalize_audio_device(options.processing_device) == AUTO_AUDIO_DEVICE
        and method == DEMUCS_METHOD
        and resolved_device == CPU_AUDIO_DEVICE
    ):
        warnings.append("Demucs đang chạy CPU vì DirectML không hỗ trợ model này.")

    project_name = options.project_name.strip() or input_path.stem
    project_dir = unique_project_dir(options.output_dir, project_name, fallback_prefix="audio")
    manifest_path = project_dir / "audio_separation_manifest.json"
    try:
        with tempfile.TemporaryDirectory(prefix="galaxy_audio_separator_") as temp_dir:
            working_input = input_path
            if input_path.suffix.lower() in VIDEO_EXTENSIONS or options.sample_mode:
                ffmpeg = ffmpeg_path or find_ffmpeg()
                if not ffmpeg:
                    raise RuntimeError(ffmpeg_missing_message("prepare audio for stem separation"))
                working_input = Path(temp_dir) / "prepared_input.wav"
                report("Đang chuẩn bị audio stereo 44.1 kHz...")
                _run_streaming_command(
                    build_prepare_audio_command(
                        ffmpeg,
                        input_path,
                        working_input,
                        sample_mode=options.sample_mode,
                    ),
                    report,
                    cancellation,
                )
                if not working_input.is_file() or working_input.stat().st_size == 0:
                    raise RuntimeError("FFmpeg không tạo được audio đầu vào cho UVR.")

            report(
                f"Đang chạy {AUDIO_PROCESS_METHOD_LABELS[method]} với {model.label} "
                f"trên {AUDIO_PROCESSING_DEVICE_LABELS[resolved_device]}..."
            )
            command = build_audio_separator_command(
                selected_runtime,
                options,
                model,
                project_dir,
                working_input,
                resolved_device,
            )
            environment = os.environ.copy()
            if resolved_device == CPU_AUDIO_DEVICE:
                environment["CUDA_VISIBLE_DEVICES"] = ""
            bundled_ffmpeg = find_ffmpeg()
            if bundled_ffmpeg:
                environment["PATH"] = (
                    f"{Path(bundled_ffmpeg).parent}{os.pathsep}{environment.get('PATH', '')}"
                )
            _run_streaming_command(command, report, cancellation, env=environment)

        extension = f".{options.output_format.strip().lower()}"
        output_paths = tuple(
            sorted(
                path
                for path in project_dir.glob(f"*{extension}")
                if path.is_file() and path.stat().st_size > 0
            )
        )
        if not output_paths:
            raise RuntimeError("Engine đã kết thúc nhưng không tạo được file stem nào.")

        write_json_atomic(
            manifest_path,
            {
                "app": "Galaxy AI Voice & Subtitle Studio",
                "version": "1.0",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source": str(input_path),
                "engine": "audio-separator",
                "credits": "Ultimate Vocal Remover by Anjok07 and the selected model authors",
                "uvr_root": str(Path(uvr_root or default_uvr_root()).expanduser()),
                "method": method,
                "model": model.filename,
                "device": resolved_device,
                "output_format": options.output_format.strip().upper(),
                "segment_size": options.segment_size,
                "overlap": options.overlap,
                "vocals_only": options.vocals_only,
                "instrumental_only": options.instrumental_only,
                "sample_mode": options.sample_mode,
                "files": [path.name for path in output_paths],
                "warnings": warnings,
            },
        )
        report("Tách âm thanh hoàn tất.")
        return AudioSeparationResult(
            project_dir=project_dir,
            output_paths=output_paths,
            manifest_path=manifest_path,
            warnings=tuple(warnings),
        )
    except Exception:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise


def _run_streaming_command(
    command: list[str],
    report: ProgressCallback,
    stop_event: threading.Event,
    *,
    env: dict[str, str] | None = None,
) -> None:
    managed_media_processes.ensure_running()
    if stop_event.is_set():
        raise RuntimeError("Đã dừng tác vụ tách âm thanh.")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    managed_media_processes.add(process)
    output_tail: list[str] = []
    try:
        if process.stdout is not None:
            for line in process.stdout:
                message = line.strip()
                if message:
                    report(message)
                    output_tail.append(message)
                    del output_tail[:-12]
                if stop_event.is_set():
                    terminate_process_tree(process)
                    break
        return_code = process.wait()
    except BaseException:
        terminate_process_tree(process)
        try:
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise
    finally:
        managed_media_processes.discard(process)
        if process.stdout is not None:
            close_stdout = getattr(process.stdout, "close", None)
            try:
                if callable(close_stdout):
                    close_stdout()
            except OSError:
                pass

    if stop_event.is_set():
        raise RuntimeError("Đã dừng tác vụ tách âm thanh.")
    if return_code != 0:
        detail = "\n".join(output_tail).strip()
        raise RuntimeError(detail or f"Audio separator failed with exit code {return_code}.")
