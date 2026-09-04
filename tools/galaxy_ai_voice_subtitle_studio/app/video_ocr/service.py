from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from ..common.cache import default_cache_dir, file_digest, read_json, stable_digest
from ..common.diagnostics import redact_sensitive_text, redacted_binary_log
from ..common.errors import TaskCancelledError
from ..common.paths import studio_root, unique_project_dir
from ..common.processes import managed_media_processes, terminate_process_tree
from ..project_graph.integrations import register_media_result
from ..project_graph.service import ProjectGraphService
from ..reliability.service import guard_output_space
from .models import OcrBox, OcrCue, VideoOcrOptions, VideoOcrResult

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class VideoOcrRuntime:
    root: Path
    python_path: Path

    @property
    def ready(self) -> bool:
        return self.python_path.is_file()


def default_video_ocr_runtime() -> VideoOcrRuntime:
    configured = os.environ.get("GALAXY_VIDEO_OCR_PYTHON", "").strip()
    if configured:
        python_path = Path(configured).expanduser()
        return VideoOcrRuntime(python_path.parent.parent, python_path)
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    root = base / "GalaxyAIStudio" / "models" / "VideoOCR"
    return VideoOcrRuntime(root, root / ".venv" / "Scripts" / "python.exe")


def install_video_ocr_runtime(
    installer: Path,
    *,
    runtime: VideoOcrRuntime | None = None,
    progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
    task_id: str | None = None,
) -> dict[str, str]:
    script = Path(installer).expanduser()
    if not script.is_file():
        raise FileNotFoundError(f"Khong tim thay bo cai OCR: {script}")
    selected = runtime or default_video_ocr_runtime()
    guard_output_space(selected.root, minimum_mib=1_024)
    if stop_event is not None and stop_event.is_set():
        raise TaskCancelledError()

    selected.root.mkdir(parents=True, exist_ok=True)
    log_path = selected.root / "install.log"
    report = progress or (lambda _message: None)
    report("Dang cai runtime OCR local...")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
    ]
    try:
        with redacted_binary_log(log_path) as log_stream:
            process = subprocess.Popen(
                command,
                cwd=str(script.parent),
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            managed_media_processes.add(process, task_id=task_id)
            try:
                while process.poll() is None:
                    if stop_event is not None and stop_event.wait(0.25):
                        if task_id:
                            managed_media_processes.terminate_task(task_id)
                        else:
                            terminate_process_tree(process)
                        raise TaskCancelledError()
                if process.returncode != 0:
                    detail = _log_tail(log_path)
                    raise RuntimeError(
                        f"Cai runtime OCR that bai voi ma {process.returncode}."
                        + (f"\n{detail}" if detail else f" Xem log: {log_path}")
                    )
            finally:
                managed_media_processes.discard(process)
    except OSError as error:
        raise RuntimeError(f"Khong chay duoc bo cai OCR: {error}") from error

    if not selected.ready:
        raise RuntimeError(f"Bo cai ket thuc nhung runtime OCR chua san sang: {selected.python_path}")
    report("Runtime OCR local da san sang.")
    return {"python_path": str(selected.python_path), "log_path": str(log_path)}


def recognize_burned_subtitles(
    options: VideoOcrOptions,
    *,
    runtime: VideoOcrRuntime | None = None,
    progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
    task_id: str | None = None,
    cache_root: Path | None = None,
) -> VideoOcrResult:
    options.validate()
    selected = runtime or default_video_ocr_runtime()
    if not selected.ready:
        raise RuntimeError("Runtime OCR local chua duoc cai.")
    if stop_event is not None and stop_event.is_set():
        raise TaskCancelledError()

    report = progress or (lambda _message: None)
    project_dir = unique_project_dir(options.output_dir, options.project_name, "ocr")
    guard_output_space(project_dir, minimum_mib=256)
    cache_dir = Path(cache_root or default_cache_dir() / "video-ocr") / _cache_key(options)
    cached = _load_cached_result(cache_dir, project_dir, options.video_path)
    if cached is not None:
        report("Da dung ket qua OCR trong bo nho dem.")
        return cached

    worker_path = Path(__file__).with_name("worker.py")
    command = build_video_ocr_command(selected, worker_path, options, project_dir)
    environment = dict(os.environ)
    python_path = str(studio_root())
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (python_path, environment.get("PYTHONPATH", "")) if item
    )
    report("Dang lay mau vung phu de va nhan dang cac khung hinh thay doi...")
    return_code, output = _run_worker(
        command,
        cwd=studio_root(),
        environment=environment,
        progress=report,
        stop_event=stop_event,
        task_id=task_id,
    )
    if return_code != 0:
        detail = "\n".join(output) or f"OCR worker exited with code {return_code}."
        raise RuntimeError(detail)
    result = _result_from_manifest(project_dir / "ocr_manifest.json", project_dir, options.video_path)
    _store_cached_result(result, cache_dir)
    return result


def register_video_ocr_result(
    service: ProjectGraphService,
    result: VideoOcrResult,
    *,
    project_id: str,
    owner_id: str,
    label: str,
    mode: str,
) -> None:
    register_media_result(
        service,
        project_id=project_id,
        workspace="editor",
        owner_id=owner_id,
        label=label,
        sources=(("source_video", str(result.source_video_path)),),
        outputs=(("ocr_subtitle", str(result.srt_path)), ("ocr_manifest", str(result.manifest_path))),
        metadata={"workflow": "burned-subtitle-ocr", "mode": mode, "cue_count": len(result.cues)},
    )


def build_video_ocr_command(
    runtime: VideoOcrRuntime,
    worker_path: Path,
    options: VideoOcrOptions,
    project_dir: Path,
) -> list[str]:
    x, y, width, height = options.region.as_tuple()
    return [
        str(runtime.python_path),
        str(worker_path),
        "--video",
        str(options.video_path),
        "--output",
        str(project_dir),
        "--mode",
        options.mode,
        "--language",
        options.language.strip() or "vi",
        "--region",
        str(x),
        str(y),
        str(width),
        str(height),
    ]


def _run_worker(
    command: list[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    progress: ProgressCallback,
    stop_event: threading.Event | None,
    task_id: str | None,
) -> tuple[int, deque[str]]:
    managed_media_processes.ensure_running()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    managed_media_processes.add(process, task_id=task_id)
    recent: deque[str] = deque(maxlen=50)
    try:
        if process.stdout is not None:
            for line in process.stdout:
                if stop_event is not None and stop_event.is_set():
                    raise TaskCancelledError()
                message = line.strip()
                if not message or message.startswith("GALAXY_OCR_RESULT:"):
                    continue
                recent.append(message)
                progress(message)
        return_code = process.wait()
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelledError()
        return return_code, recent
    except BaseException:
        terminate_process_tree(process)
        raise
    finally:
        managed_media_processes.discard(process)


def _cache_key(options: VideoOcrOptions) -> str:
    return stable_digest(
        {
            "version": 2,
            "source_sha256": file_digest(options.video_path),
            "mode": options.mode,
            "region": options.region.as_tuple(),
            "language": options.language.strip().casefold(),
        }
    )


def _load_cached_result(
    cache_dir: Path,
    project_dir: Path,
    source_video_path: Path,
) -> VideoOcrResult | None:
    manifest = cache_dir / "ocr_manifest.json"
    srt = cache_dir / "captions.srt"
    if not manifest.is_file() or not srt.is_file():
        return None
    try:
        shutil.copy2(srt, project_dir / "captions.srt")
        shutil.copy2(manifest, project_dir / "ocr_manifest.json")
        result = _result_from_manifest(project_dir / "ocr_manifest.json", project_dir, source_video_path)
    except (OSError, RuntimeError, ValueError):
        return None
    return VideoOcrResult(**{**result.__dict__, "cache_hit": True})


def _store_cached_result(result: VideoOcrResult, cache_dir: Path) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result.srt_path, cache_dir / "captions.srt")
        shutil.copy2(result.manifest_path, cache_dir / "ocr_manifest.json")
    except OSError:
        pass


def _result_from_manifest(path: Path, project_dir: Path, source_video_path: Path) -> VideoOcrResult:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise RuntimeError("OCR worker khong tao manifest hop le.")
    raw_cues = payload.get("cues")
    if not isinstance(raw_cues, list):
        raise RuntimeError("OCR manifest khong co danh sach phu de.")
    cues: list[OcrCue] = []
    for item in raw_cues:
        if not isinstance(item, dict):
            continue
        boxes = tuple(
            OcrBox(int(box["x"]), int(box["y"]), int(box["width"]), int(box["height"]))
            for box in item.get("boxes", [])
            if isinstance(box, dict)
        )
        cues.append(
            OcrCue(
                index=int(item["index"]),
                start_ms=int(item["start_ms"]),
                end_ms=int(item["end_ms"]),
                text=str(item["text"]),
                confidence=float(item.get("confidence") or 0.0),
                boxes=boxes,
            )
        )
    srt_path = project_dir / "captions.srt"
    if not srt_path.is_file():
        raise RuntimeError("OCR worker khong tao tep SRT.")
    return VideoOcrResult(
        project_dir=project_dir,
        srt_path=srt_path,
        manifest_path=path,
        source_video_path=source_video_path,
        cues=tuple(cues),
        sampled_frames=int(payload.get("sampled_frames") or 0),
        ocr_frames=int(payload.get("ocr_frames") or 0),
        reused_frames=int(payload.get("reused_frames") or 0),
        probe_runs=int(payload.get("probe_runs") or 0),
        rescue_frames=int(payload.get("rescue_frames") or 0),
        discarded_static_cues=int(payload.get("discarded_static_cues") or 0),
    )


def _log_tail(path: Path, limit: int = 2_000) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return redact_sensitive_text(raw.decode("utf-8", errors="replace")[-limit:].strip())
