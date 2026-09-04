from __future__ import annotations

import importlib.util
import ipaddress
import re
import shutil
import socket
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib.parse import urlsplit

from ....common.diagnostics import redact_sensitive_text
from ....common.errors import TaskCancelledError
from ....common.ffmpeg import find_ffmpeg
from ....common.paths import unique_project_dir
from ....common.processes import managed_media_processes, terminate_process_tree
from ....reliability.service import guard_output_space


VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".webm"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".flac", ".m4a"})
SUPPORTED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
_PROGRESS_PATTERN = re.compile(r"__GALAXY_PROGRESS__\s*([0-9]+(?:\.[0-9]+)?)%")
_COOKIE_HEADERS = ("# Netscape HTTP Cookie File", "# HTTP Cookie File")

ProgressCallback = Callable[[str, float | None], None]
HostResolver = Callable[[str], Iterable[str]]
DownloaderRunner = Callable[..., None]


@dataclass(frozen=True)
class DubbingCaptionArtifact:
    path: str
    language: str
    kind: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "language": self.language, "kind": self.kind, "text": self.text}


@dataclass(frozen=True)
class DubbingIngestResult:
    source_path: str
    source_kind: str
    source_name: str
    source_url: str = ""
    project_dir: str = ""
    captions: tuple[DubbingCaptionArtifact, ...] = ()
    selected_caption: DubbingCaptionArtifact | None = None
    translated_caption: DubbingCaptionArtifact | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "project_dir": self.project_dir,
            "captions": [item.to_dict() for item in self.captions],
            "selected_caption": self.selected_caption.to_dict() if self.selected_caption else None,
            "translated_caption": self.translated_caption.to_dict() if self.translated_caption else None,
            "warnings": list(self.warnings),
        }


def default_downloader_command() -> tuple[str, ...]:
    executable = shutil.which("yt-dlp")
    if executable:
        return (executable,)
    if importlib.util.find_spec("yt_dlp") is not None:
        return (sys.executable, "-m", "yt_dlp")
    return ()


def validate_remote_media_url(value: str, *, host_resolver: HostResolver | None = None) -> str:
    url = value.strip()
    parsed = urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL media phải dùng http hoặc https.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL không được chứa thông tin đăng nhập.")
    addresses = tuple((host_resolver or _resolve_host)(parsed.hostname))
    if not addresses:
        raise ValueError("Không phân giải được tên miền media.")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as error:
            raise ValueError("Địa chỉ media không hợp lệ.") from error
        if not ip.is_global:
            raise ValueError("URL trỏ đến mạng nội bộ nên đã bị từ chối.")
    return url


def validate_cookie_file(path: Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file() or resolved.suffix.casefold() != ".txt":
        raise ValueError("Cookie phải là file Netscape .txt hợp lệ.")
    try:
        with resolved.open("r", encoding="utf-8", errors="replace") as stream:
            first_line = stream.readline(256).strip()
    except OSError as error:
        raise ValueError("Không đọc được file cookie.") from error
    if not first_line.startswith(_COOKIE_HEADERS):
        raise ValueError("File cookie không đúng định dạng Netscape.")
    return resolved


def build_download_command(
    downloader_command: Sequence[str],
    url: str,
    output_dir: Path,
    *,
    pull_captions: bool,
    source_language: str,
    target_language: str,
    cookie_path: Path | None = None,
    ffmpeg_path: str | None = None,
) -> list[str]:
    command = [
        *downloader_command,
        "--no-playlist",
        "--playlist-items", "1",
        "--max-downloads", "1",
        "--newline",
        "--progress-template", "download:__GALAXY_PROGRESS__%(progress._percent_str)s",
        "--paths", str(output_dir),
        "--output", "%(title).120s-%(id)s.%(ext)s",
        "--merge-output-format", "mp4",
        "--write-info-json",
    ]
    if pull_captions:
        command.extend([
            "--write-subs", "--write-auto-subs", "--sub-format", "srt",
            "--convert-subs", "srt", "--sub-langs",
            _subtitle_language_filter(source_language, target_language),
        ])
    if cookie_path is not None:
        command.extend(["--cookies", str(cookie_path)])
    if ffmpeg_path:
        command.extend(["--ffmpeg-location", ffmpeg_path])
    command.append(url)
    return command


class DubbingIngestService:
    def __init__(
        self,
        *,
        downloader_command: Sequence[str] | None = None,
        host_resolver: HostResolver | None = None,
        downloader_runner: DownloaderRunner | None = None,
    ) -> None:
        self.downloader_command = tuple(
            default_downloader_command() if downloader_command is None else downloader_command
        )
        self.host_resolver = host_resolver or _resolve_host
        self.downloader_runner = downloader_runner or _run_downloader

    def adapter_status(self) -> dict[str, object]:
        available = bool(self.downloader_command)
        return {
            "available": available,
            "name": "yt-dlp",
            "message": "yt-dlp sẵn sàng." if available else "Chưa có yt-dlp. Cài bằng lệnh: py -m pip install yt-dlp",
        }

    def ingest_local(
        self,
        media_path: str | Path,
        *,
        source_language: str = "auto",
        target_language: str = "",
    ) -> DubbingIngestResult:
        source = _validate_media_path(media_path)
        captions = _discover_captions(source.parent, source.stem)
        selected, translated = _select_captions(captions, source_language, target_language)
        return DubbingIngestResult(
            source_path=str(source),
            source_kind=_source_kind(source),
            source_name=source.stem,
            captions=captions,
            selected_caption=selected,
            translated_caption=translated,
        )

    def ingest_url(
        self,
        url: str,
        output_root: str | Path,
        *,
        pull_captions: bool = False,
        source_language: str = "auto",
        target_language: str = "",
        cookie_path: str | Path | None = None,
        progress: ProgressCallback | None = None,
        stop_event: threading.Event | None = None,
        task_id: str | None = None,
    ) -> DubbingIngestResult:
        if not self.downloader_command:
            raise RuntimeError("Chưa có yt-dlp. Cài bằng lệnh: py -m pip install yt-dlp")
        safe_url = validate_remote_media_url(url, host_resolver=self.host_resolver)
        cookie = validate_cookie_file(Path(cookie_path)) if cookie_path else None
        root = Path(output_root).expanduser().resolve()
        guard_output_space(root, minimum_mib=1024)
        project_dir = unique_project_dir(root, "dubbing-ingest", fallback_prefix="dubbing-ingest")
        command = build_download_command(
            self.downloader_command, safe_url, project_dir,
            pull_captions=pull_captions,
            source_language=source_language,
            target_language=target_language,
            cookie_path=cookie,
            ffmpeg_path=find_ffmpeg(),
        )
        report = progress or (lambda _message, _value=None: None)
        try:
            report("Đang tải media...", 0.0)
            self.downloader_runner(
                command, project_dir, progress=report, stop_event=stop_event,
                task_id=task_id, cookie_path=cookie,
            )
            media = sorted(
                (item.resolve() for item in project_dir.iterdir() if item.suffix.casefold() in SUPPORTED_EXTENSIONS),
                key=lambda item: item.name.casefold(),
            )
            if not media:
                raise RuntimeError("yt-dlp không tạo được file media được hỗ trợ.")
            source = media[0]
            captions = _discover_captions(project_dir, "")
            selected, translated = _select_captions(captions, source_language, target_language)
            warnings = () if captions or not pull_captions else ("Không tìm thấy caption phù hợp.",)
            report("Đã nhập media.", 1.0)
            return DubbingIngestResult(
                source_path=str(source), source_kind=_source_kind(source), source_name=source.stem,
                source_url=safe_url, project_dir=str(project_dir.resolve()), captions=captions,
                selected_caption=selected, translated_caption=translated, warnings=warnings,
            )
        except BaseException:
            shutil.rmtree(project_dir, ignore_errors=True)
            raise


def _validate_media_path(media_path: str | Path) -> Path:
    path = Path(media_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy media: {path}")
    if path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
        raise ValueError("File media có định dạng không được hỗ trợ.")
    return path


def _source_kind(path: Path) -> str:
    return "video" if path.suffix.casefold() in VIDEO_EXTENSIONS else "audio"


def _discover_captions(directory: Path, media_stem: str) -> tuple[DubbingCaptionArtifact, ...]:
    matches: list[DubbingCaptionArtifact] = []
    for path in sorted(directory.glob("*.srt"), key=lambda item: item.name.casefold())[:100]:
        if media_stem and path.stem != media_stem and not path.stem.startswith(f"{media_stem}."):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        language = _caption_language(path, media_stem)
        kind = "automatic" if ".auto." in path.name.casefold() else "caption"
        matches.append(DubbingCaptionArtifact(str(path.resolve()), language, kind, text))
    return tuple(matches)


def _caption_language(path: Path, media_stem: str) -> str:
    stem = path.stem
    suffix = stem[len(media_stem):].lstrip(".") if media_stem and stem.startswith(media_stem) else ""
    if not suffix:
        parts = stem.rsplit(".", 1)
        suffix = parts[-1] if len(parts) == 2 else "und"
    return suffix.split(".", 1)[0].replace("_", "-").casefold() or "und"


def _select_captions(
    captions: tuple[DubbingCaptionArtifact, ...], source_language: str, target_language: str,
) -> tuple[DubbingCaptionArtifact | None, DubbingCaptionArtifact | None]:
    target = _best_caption(captions, target_language) if target_language else None
    if source_language.strip().casefold() in {"", "auto"}:
        source = next((item for item in captions if item != target), captions[0] if captions else None)
    else:
        source = _best_caption(captions, source_language) or next(
            (item for item in captions if item.language == "und"), None
        )
    return source, target if target != source else None


def _best_caption(captions: tuple[DubbingCaptionArtifact, ...], language: str) -> DubbingCaptionArtifact | None:
    desired = language.strip().replace("_", "-").casefold()
    if not desired:
        return None
    base = desired.split("-", 1)[0]
    ranked = sorted(captions, key=lambda item: (
        0 if item.language == desired else 1 if item.language.split("-", 1)[0] == base else 2,
        item.path.casefold(),
    ))
    return ranked[0] if ranked and ranked[0].language.split("-", 1)[0] == base else None


def _subtitle_language_filter(source_language: str, target_language: str) -> str:
    languages: list[str] = []
    for raw in (source_language, target_language):
        language = raw.strip().replace("_", "-").casefold()
        if language and language != "auto" and language not in languages:
            languages.append(language)
    if not languages:
        return "all,-live_chat"
    return ",".join(f"{item}.*" for item in languages) + ",-live_chat"


def _resolve_host(host: str) -> tuple[str, ...]:
    try:
        return tuple(sorted({item[4][0] for item in socket.getaddrinfo(host, None)}))
    except socket.gaierror as error:
        raise ValueError("Không phân giải được tên miền media.") from error


def _run_downloader(
    command: Sequence[str], output_dir: Path, *, progress: ProgressCallback,
    stop_event: threading.Event | None, task_id: str | None, cookie_path: Path | None,
) -> None:
    del output_dir
    managed_media_processes.ensure_running()
    process = subprocess.Popen(
        list(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    managed_media_processes.add(process, task_id=task_id)
    recent: deque[str] = deque(maxlen=80)
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                if stop_event is not None and stop_event.is_set():
                    raise TaskCancelledError()
                line = raw_line.strip()
                if not line:
                    continue
                recent.append(line)
                match = _PROGRESS_PATTERN.search(line)
                if match:
                    percentage = float(match.group(1))
                    progress(f"Đang tải {match.group(1)}%...", percentage / 100.0)
        return_code = process.wait()
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelledError()
        if return_code not in {0, 101}:
            diagnostic = "\n".join(recent)
            if cookie_path is not None:
                diagnostic = diagnostic.replace(str(cookie_path), "[REDACTED]")
            raise RuntimeError(redact_sensitive_text(diagnostic or f"yt-dlp dừng với mã {return_code}."))
    except BaseException:
        terminate_process_tree(process)
        raise
    finally:
        managed_media_processes.discard(process)
