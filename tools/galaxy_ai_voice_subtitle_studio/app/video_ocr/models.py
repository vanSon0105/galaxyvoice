from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

OCR_FAST_MODE = "fast"
OCR_ACCURATE_MODE = "accurate"
OCR_MODES = (OCR_FAST_MODE, OCR_ACCURATE_MODE)


@dataclass(frozen=True)
class VideoOcrRegion:
    x: int = 5
    y: int = 68
    width: int = 90
    height: int = 27

    def validate(self) -> None:
        if self.x < 0 or self.y < 0 or self.width < 1 or self.height < 1:
            raise ValueError("Vung OCR khong hop le.")
        if self.x + self.width > 100 or self.y + self.height > 100:
            raise ValueError("Vung OCR phai nam hoan toan trong khung hinh.")

    def as_tuple(self) -> tuple[int, int, int, int]:
        self.validate()
        return self.x, self.y, self.width, self.height


@dataclass(frozen=True)
class OcrBox:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class OcrObservation:
    timestamp_ms: int
    text: str
    confidence: float = 0.0
    boxes: tuple[OcrBox, ...] = ()


@dataclass(frozen=True)
class OcrCue:
    index: int
    start_ms: int
    end_ms: int
    text: str
    confidence: float
    boxes: tuple[OcrBox, ...] = ()


@dataclass(frozen=True)
class VideoOcrOptions:
    video_path: Path
    output_dir: Path
    project_name: str = ""
    mode: str = OCR_FAST_MODE
    region: VideoOcrRegion = VideoOcrRegion()
    language: str = "vi"

    def validate(self) -> None:
        if not self.video_path.is_file():
            raise ValueError("Video dau vao khong ton tai.")
        if self.mode not in OCR_MODES:
            raise ValueError("Che do OCR khong hop le.")
        self.region.validate()


@dataclass(frozen=True)
class VideoOcrResult:
    project_dir: Path
    srt_path: Path
    manifest_path: Path
    source_video_path: Path
    cues: tuple[OcrCue, ...]
    sampled_frames: int
    ocr_frames: int
    reused_frames: int
    probe_runs: int = 0
    rescue_frames: int = 0
    discarded_static_cues: int = 0
    cache_hit: bool = False

    def to_payload(self) -> dict[str, object]:
        return {
            "project_dir": str(self.project_dir),
            "srt_path": str(self.srt_path),
            "manifest_path": str(self.manifest_path),
            "source_video_path": str(self.source_video_path),
            "cues": [
                {
                    "index": cue.index,
                    "start_ms": cue.start_ms,
                    "end_ms": cue.end_ms,
                    "text": cue.text,
                    "confidence": cue.confidence,
                    "boxes": [box.__dict__ for box in cue.boxes],
                }
                for cue in self.cues
            ],
            "sampled_frames": self.sampled_frames,
            "ocr_frames": self.ocr_frames,
            "reused_frames": self.reused_frames,
            "probe_runs": self.probe_runs,
            "rescue_frames": self.rescue_frames,
            "discarded_static_cues": self.discarded_static_cues,
            "cache_hit": self.cache_hit,
        }
