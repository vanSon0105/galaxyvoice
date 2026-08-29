from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


SUPPORTED_AUDIO_FORMATS = ("wav", "mp3", "flac", "m4a")
SUPPORTED_POST_PRESETS = ("none", "voice_clean", "podcast")


@dataclass(frozen=True)
class AudioSource:
    source_id: str
    path: Path
    role: str = "voice"
    selected: bool = True
    gain_db: float = 0.0


@dataclass(frozen=True)
class SegmentGain:
    start_ms: int
    end_ms: int
    gain_db: float


@dataclass(frozen=True)
class AudioPostChain:
    trim_start_ms: int = 0
    trim_end_ms: int | None = None
    gain_db: float = 0.0
    segment_gains: tuple[SegmentGain, ...] = ()
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    normalize: bool = False
    target_lufs: float = -16.0
    true_peak_db: float = -1.0
    loudness_range: float = 11.0
    preset: str = "none"
    trim_silence: bool = False


@dataclass(frozen=True)
class ExportMetadata:
    title: str = ""
    artist: str = ""
    album: str = ""
    comment: str = ""


@dataclass(frozen=True)
class AudioExportRequest:
    project_id: str
    workflow_id: str
    workspace: str
    project_dir: Path
    title: str
    sources: tuple[AudioSource, ...]
    formats: tuple[str, ...] = ("wav",)
    chain: AudioPostChain = field(default_factory=AudioPostChain)
    metadata: ExportMetadata = field(default_factory=ExportMetadata)
    sample_rate: int = 48_000
    channels: int = 2
    bitrate_kbps: int = 192

    def validate(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id is required.")
        if not self.workflow_id.strip():
            raise ValueError("workflow_id is required.")
        if not self.workspace.strip():
            raise ValueError("workspace is required.")
        selected = [source for source in self.sources if source.selected]
        if not selected:
            raise ValueError("Select at least one audio source.")
        missing = [str(source.path) for source in selected if not source.path.is_file()]
        if missing:
            raise ValueError(f"Audio source does not exist: {missing[0]}")
        formats = tuple(dict.fromkeys(item.casefold() for item in self.formats))
        unsupported = [item for item in formats if item not in SUPPORTED_AUDIO_FORMATS]
        if not formats or unsupported:
            raise ValueError(f"Unsupported audio format: {', '.join(unsupported) or '(empty)'}")
        if self.chain.trim_start_ms < 0:
            raise ValueError("trim_start_ms cannot be negative.")
        if self.chain.trim_end_ms is not None and self.chain.trim_end_ms <= self.chain.trim_start_ms:
            raise ValueError("trim_end_ms must be greater than trim_start_ms.")
        if self.chain.preset not in SUPPORTED_POST_PRESETS:
            raise ValueError(f"Unsupported audio preset: {self.chain.preset}")
        for segment in self.chain.segment_gains:
            if segment.start_ms < 0 or segment.end_ms <= segment.start_ms:
                raise ValueError("Segment gain range is invalid.")
        if self.sample_rate < 8_000 or self.channels not in {1, 2}:
            raise ValueError("Audio sample rate or channel count is invalid.")


@dataclass(frozen=True)
class WaveformData:
    duration_ms: int
    peaks: tuple[float, ...]
    cache_path: Path


@dataclass(frozen=True)
class AudioExportResult:
    export_id: str
    project_dir: Path
    files: dict[str, Path]
    manifest_path: Path
    warnings: tuple[str, ...] = ()
