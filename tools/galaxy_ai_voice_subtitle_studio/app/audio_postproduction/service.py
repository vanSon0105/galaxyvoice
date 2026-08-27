from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import uuid
import wave
from array import array
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..common.cache import file_digest, read_json, stable_digest, write_json_atomic
from ..common.ffmpeg import find_ffmpeg, find_ffprobe
from ..common.paths import slugify
from .models import AudioExportRequest, AudioExportResult, AudioSource, WaveformData


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
AudioProbe = Callable[[Path], dict[str, int]]


class AudioPostproductionService:
    """Applies one reusable post chain and records every export in its project."""

    def __init__(
        self,
        *,
        ffmpeg: str | None = None,
        ffprobe: str | None = None,
        runner: CommandRunner | None = None,
        probe: AudioProbe | None = None,
    ) -> None:
        self.ffmpeg = ffmpeg or find_ffmpeg()
        self.ffprobe = ffprobe or find_ffprobe()
        self._runner = runner or self._run
        self._probe = probe or self._probe_audio

    def waveform(self, source: Path, *, project_dir: Path, points: int = 256) -> WaveformData:
        source = Path(source).resolve()
        project_dir = self._ensure_project_dir(project_dir)
        if not source.is_file():
            raise ValueError(f"Audio source does not exist: {source}")
        points = max(16, min(int(points), 2_048))
        key = stable_digest({"sha256": file_digest(source), "points": points})
        cache_path = project_dir / ".cache" / "waveforms" / f"{key}.json"
        cached = read_json(cache_path)
        if isinstance(cached, dict) and isinstance(cached.get("peaks"), list):
            peaks = tuple(float(value) for value in cached["peaks"])
            if len(peaks) == points:
                return WaveformData(int(cached.get("duration_ms", 0)), peaks, cache_path)

        wav_source = source
        temporary: Path | None = None
        if source.suffix.casefold() != ".wav":
            temporary = self._decode_waveform_source(source, cache_path)
            wav_source = temporary
        try:
            try:
                duration_ms, peaks = self._wav_peaks(wav_source, points)
            except (ValueError, wave.Error, EOFError):
                if temporary is not None:
                    raise
                temporary = self._decode_waveform_source(source, cache_path)
                duration_ms, peaks = self._wav_peaks(temporary, points)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        write_json_atomic(cache_path, {"duration_ms": duration_ms, "peaks": list(peaks)})
        return WaveformData(duration_ms, peaks, cache_path)

    def _decode_waveform_source(self, source: Path, cache_path: Path) -> Path:
        if not self.ffmpeg:
            raise ValueError("ffmpeg is required to decode this audio format.")
        temporary = cache_path.with_suffix(".source.wav")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        self._run_checked([
            self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
            "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", str(temporary),
        ])
        return temporary

    def export(self, request: AudioExportRequest) -> AudioExportResult:
        request.validate()
        project_dir = self._ensure_project_dir(request.project_dir)
        self._bind_project_identity(project_dir, request.project_id, request.workspace)
        if not self.ffmpeg:
            raise ValueError("ffmpeg is required for audio postproduction.")
        export_id = uuid.uuid4().hex
        export_dir = project_dir / "exports" / "audio" / export_id
        export_dir.mkdir(parents=True, exist_ok=False)
        title_slug = slugify(request.title) or "audio-export"
        selected = tuple(source for source in request.sources if source.selected)
        master_path = export_dir / f"{title_slug}.master.wav"
        try:
            command = self._render_command(request, selected, master_path)
            self._run_checked(command)

            outputs: dict[str, Path] = {}
            formats = tuple(dict.fromkeys(item.casefold() for item in request.formats))
            for format_name in formats:
                output = export_dir / f"{title_slug}.{format_name}"
                self._run_checked(self._conversion_command(request, master_path, output, format_name))
                outputs[format_name] = output
            master_path.unlink(missing_ok=True)

            manifest_path = export_dir / "audio_export_manifest.json"
            manifest = {
                "schema_version": 1,
                "export_id": export_id,
                "project_id": request.project_id,
                "workspace": request.workspace,
                "title": request.title,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "sources": [self._source_trace(source, project_dir) for source in selected],
                "chain": asdict(request.chain),
                "metadata": asdict(request.metadata),
                "settings": {
                    "sample_rate": request.sample_rate,
                    "channels": request.channels,
                    "bitrate_kbps": request.bitrate_kbps,
                },
                "files": {name: path.relative_to(project_dir).as_posix() for name, path in outputs.items()},
            }
            write_json_atomic(manifest_path, manifest)
        except Exception:
            shutil.rmtree(export_dir, ignore_errors=True)
            raise
        return AudioExportResult(export_id, project_dir, outputs, manifest_path)

    def master_wav_in_place(
        self,
        wav_path: Path,
        *,
        target_lufs: float = -16.0,
        true_peak_db: float = -1.0,
        loudness_range: float = 11.0,
    ) -> tuple[bool, str]:
        """Atomically master a WAV while preserving the source on failure."""

        if not self.ffmpeg:
            return False, "Không tìm thấy ffmpeg; đã giữ nguyên WAV chưa mastering."
        target = max(-24.0, min(-9.0, float(target_lufs)))
        peak = max(-6.0, min(-0.1, float(true_peak_db)))
        loudness_range = max(1.0, min(30.0, float(loudness_range)))
        temporary = wav_path.with_name(f"{wav_path.stem}.mastered.wav")
        try:
            self._run_checked([
                self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav_path),
                "-af", f"loudnorm=I={target:.1f}:TP={peak:.1f}:LRA={loudness_range:g}",
                "-c:a", "pcm_s16le", str(temporary),
            ])
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise RuntimeError("ffmpeg did not create the mastered WAV.")
        except RuntimeError as error:
            temporary.unlink(missing_ok=True)
            return False, f"Mastering thất bại; đã giữ nguyên WAV: {error}"
        temporary.replace(wav_path)
        return True, "Mastering completed."

    def resolve_export(self, project_dir: Path, export_id: str, format_name: str) -> Path:
        project_dir = self._ensure_project_dir(project_dir)
        if not re.fullmatch(r"[0-9a-f]{32}", export_id):
            raise ValueError("Audio export does not exist.")
        manifest_path = project_dir / "exports" / "audio" / export_id / "audio_export_manifest.json"
        payload = read_json(manifest_path)
        if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
            raise ValueError("Audio export does not exist.")
        relative = payload["files"].get(format_name.casefold())
        if not isinstance(relative, str):
            raise ValueError("Audio export format does not exist.")
        resolved = (project_dir / relative).resolve()
        if not resolved.is_relative_to(project_dir) or not resolved.is_file():
            raise ValueError("Audio export file is unavailable.")
        return resolved

    def list_exports(self, project_dir: Path) -> list[dict[str, object]]:
        project_dir = self._ensure_project_dir(project_dir)
        root = project_dir / "exports" / "audio"
        exports = []
        for path in root.glob("*/audio_export_manifest.json") if root.is_dir() else ():
            payload = read_json(path)
            if isinstance(payload, dict):
                exports.append(payload)
        return sorted(exports, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def discover_sources(self, project_dir: Path) -> list[AudioSource]:
        project_dir = self._ensure_project_dir(project_dir)
        sources: list[AudioSource] = []
        for path in sorted(project_dir.rglob("*")):
            if not path.is_file() or path.suffix.casefold().lstrip(".") not in {"wav", "mp3", "flac", "m4a"}:
                continue
            relative = path.relative_to(project_dir)
            if relative.parts and relative.parts[0] in {"exports", ".cache"}:
                continue
            role = "stem" if "stems" in {part.casefold() for part in relative.parts} else "voice"
            sources.append(AudioSource(stable_digest(relative.as_posix())[:16], path, role=role))
            if len(sources) >= 1_000:
                break
        return sources

    def _render_command(
        self, request: AudioExportRequest, sources: tuple[AudioSource, ...], output: Path
    ) -> list[str]:
        command = [self.ffmpeg or "ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for source in sources:
            command.extend(("-i", str(source.path)))
        filters: list[str] = []
        labels: list[str] = []
        for index, source in enumerate(sources):
            pieces = []
            chain = request.chain
            trim = f"atrim=start={chain.trim_start_ms / 1000:.6f}"
            if chain.trim_end_ms is not None:
                trim += f":end={chain.trim_end_ms / 1000:.6f}"
            pieces.extend((trim, "asetpts=PTS-STARTPTS"))
            if chain.trim_silence:
                pieces.extend((
                    "silenceremove=start_periods=1:start_duration=0.08:start_threshold=-48dB",
                    "areverse",
                    "silenceremove=start_periods=1:start_duration=0.15:start_threshold=-48dB",
                    "areverse",
                ))
            pieces.extend(self._preset_filters(chain.preset))
            if source.gain_db:
                pieces.append(f"volume={source.gain_db:g}dB")
            for segment in chain.segment_gains:
                pieces.append(
                    f"volume={segment.gain_db:g}dB:enable='between(t,{segment.start_ms / 1000:.6f},{segment.end_ms / 1000:.6f})'"
                )
            label = f"s{index}"
            filters.append(f"[{index}:a]{','.join(pieces)}[{label}]")
            labels.append(f"[{label}]")
        current = "mix"
        if len(labels) == 1:
            filters.append(f"{labels[0]}anull[{current}]")
        else:
            filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0[{current}]")
        final: list[str] = []
        if request.chain.gain_db:
            final.append(f"volume={request.chain.gain_db:g}dB")
        if request.chain.fade_in_ms:
            final.append(f"afade=t=in:st=0:d={request.chain.fade_in_ms / 1000:.6f}")
        if request.chain.fade_out_ms:
            duration_ms = request.chain.trim_end_ms
            if duration_ms is None:
                duration_ms = max(self._probe(source.path).get("duration_ms", 0) for source in sources)
            duration_ms -= request.chain.trim_start_ms
            start = max(0, duration_ms - request.chain.fade_out_ms) / 1000
            final.append(f"afade=t=out:st={start:.6f}:d={request.chain.fade_out_ms / 1000:.6f}")
        if request.chain.normalize:
            final.append(
                f"loudnorm=I={request.chain.target_lufs:g}:TP={request.chain.true_peak_db:g}:LRA={request.chain.loudness_range:g}"
            )
        final.extend((f"aresample={request.sample_rate}", f"aformat=channel_layouts={'mono' if request.channels == 1 else 'stereo'}"))
        filters.append(f"[{current}]{','.join(final)}[out]")
        command.extend(("-filter_complex", ";".join(filters), "-map", "[out]", "-c:a", "pcm_s16le", str(output)))
        return command

    def _conversion_command(
        self, request: AudioExportRequest, source: Path, output: Path, format_name: str
    ) -> list[str]:
        codecs = {
            "wav": ("pcm_s16le", []),
            "mp3": ("libmp3lame", ["-b:a", f"{request.bitrate_kbps}k"]),
            "flac": ("flac", []),
            "m4a": ("aac", ["-b:a", f"{request.bitrate_kbps}k"]),
        }
        codec, options = codecs[format_name]
        command = [self.ffmpeg or "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-c:a", codec, *options]
        for key, value in asdict(request.metadata).items():
            if value.strip():
                command.extend(("-metadata", f"{key}={value.strip()}"))
        command.append(str(output))
        return command

    @staticmethod
    def _preset_filters(preset: str) -> list[str]:
        if preset == "voice_clean":
            return ["highpass=f=70", "lowpass=f=15000", "acompressor=threshold=-18dB:ratio=2.5:attack=15:release=160"]
        if preset == "podcast":
            return ["highpass=f=65", "equalizer=f=3500:t=q:w=1:g=2", "acompressor=threshold=-20dB:ratio=3:attack=10:release=180"]
        return []

    @staticmethod
    def _wav_peaks(path: Path, points: int) -> tuple[int, tuple[float, ...]]:
        with wave.open(str(path), "rb") as source:
            frame_count = source.getnframes()
            sample_rate = source.getframerate()
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            if sample_width != 2:
                raise ValueError("Waveform currently requires 16-bit PCM WAV audio.")
            frames_per_bucket = max(1, math.ceil(frame_count / points))
            peaks = []
            for _bucket in range(points):
                remaining = min(frames_per_bucket, max(0, frame_count - source.tell()))
                peak = 0
                while remaining:
                    chunk_frames = min(65_536, remaining)
                    samples = array("h", source.readframes(chunk_frames))
                    if samples:
                        peak = max(peak, max(samples), -min(samples))
                    remaining -= chunk_frames
                peaks.append(peak)
        duration_ms = round(frame_count * 1000 / sample_rate) if sample_rate else 0
        return duration_ms, tuple(round(min(1.0, peak / 32768), 5) for peak in peaks)

    def _probe_audio(self, path: Path) -> dict[str, int]:
        if self.ffprobe:
            completed = subprocess.run(
                [self.ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate,channels:format=duration", "-of", "json", str(path)],
                capture_output=True, text=True, check=False,
            )
            if completed.returncode == 0:
                payload = json.loads(completed.stdout or "{}")
                stream = (payload.get("streams") or [{}])[0]
                return {"duration_ms": round(float((payload.get("format") or {}).get("duration", 0)) * 1000), "sample_rate": int(stream.get("sample_rate", 0)), "channels": int(stream.get("channels", 0))}
        with wave.open(str(path), "rb") as source:
            return {"duration_ms": round(source.getnframes() * 1000 / source.getframerate()), "sample_rate": source.getframerate(), "channels": source.getnchannels()}

    @staticmethod
    def _source_trace(source: AudioSource, project_dir: Path) -> dict[str, object]:
        resolved = source.path.resolve()
        managed = resolved.is_relative_to(project_dir)
        return {
            "source_id": source.source_id,
            "role": source.role,
            "gain_db": source.gain_db,
            "path": resolved.relative_to(project_dir).as_posix() if managed else str(resolved),
            "path_kind": "managed" if managed else "linked",
            "sha256": file_digest(resolved),
        }

    @staticmethod
    def _bind_project_identity(project_dir: Path, project_id: str, workspace: str) -> None:
        identity_path = project_dir / ".galaxy" / "project_identity.json"
        existing = read_json(identity_path)
        identity = {"project_id": project_id, "workspace": workspace}
        if isinstance(existing, dict):
            if existing.get("project_id") != project_id or existing.get("workspace") != workspace:
                raise ValueError("Project directory belongs to a different Galaxy project or workspace.")
            return
        write_json_atomic(identity_path, identity)

    @staticmethod
    def _ensure_project_dir(project_dir: Path) -> Path:
        path = Path(project_dir).resolve()
        if path.exists() and not path.is_dir():
            raise ValueError(f"Project path is not a directory: {path}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def _run_checked(self, command: list[str]) -> None:
        completed = self._runner(command)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "ffmpeg audio operation failed.")
