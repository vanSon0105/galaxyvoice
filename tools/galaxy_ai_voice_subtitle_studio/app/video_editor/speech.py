from __future__ import annotations

import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..common.errors import TaskCancelledError
from ..common.paths import unique_project_dir
from ..studio.models import StudioGenerationSpec, StudioVoiceSelection
from ..studio.service import StudioEngine


EditorSpeechProgress = Callable[[str, float], None]
EditorSpeechCheckpoint = Callable[[dict[str, object]], None]
EditorSpeechControl = Callable[[], None]
EditorSpeechItemCallback = Callable[["EditorSpeechItemResult"], None]
_SAFE_ITEM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class EditorSpeechCueSpec:
    item_id: str
    track_id: str
    cue_id: str
    start_ms: int
    text: str
    language: str = ""

    def validate(self) -> None:
        if not _SAFE_ITEM_ID.fullmatch(self.item_id):
            raise ValueError(f"ID audio không hợp lệ: {self.item_id}")
        if not self.track_id.strip() or not self.cue_id.strip():
            raise ValueError("Mỗi câu phụ đề phải giữ track_id và cue_id.")
        if self.start_ms < 0:
            raise ValueError("Thời điểm bắt đầu audio không được âm.")
        if not self.text.strip():
            raise ValueError(f"Câu {self.cue_id} chưa có nội dung.")


@dataclass(frozen=True)
class EditorSpeechSpec:
    job_id: str
    project_id: str
    title: str
    output_dir: str
    engine_id: str = "omnivoice"
    model_id: str = "k2-fsa/OmniVoice"
    device: str = "auto"
    language: str = "vi"
    speed: float = 1.0
    voice: StudioVoiceSelection = field(default_factory=StudioVoiceSelection)
    engine_options: dict[str, Any] = field(default_factory=dict)
    cues: tuple[EditorSpeechCueSpec, ...] = ()

    def validate(self) -> None:
        if not self.job_id.strip():
            raise ValueError("Editor speech job chưa có ID.")
        if not self.project_id.strip():
            raise ValueError("Hãy chọn hoặc tạo project trước khi tạo giọng.")
        if not self.output_dir.strip():
            raise ValueError("Hãy chọn thư mục xuất trước khi tạo giọng.")
        if not self.engine_id.strip():
            raise ValueError("Editor speech job chưa chỉ định engine.")
        if not 0.5 <= self.speed <= 1.5:
            raise ValueError("Tốc độ phải từ 0.5 đến 1.5.")
        if not self.cues:
            raise ValueError("Không có câu phụ đề nào để tạo giọng.")
        item_ids: set[str] = set()
        for cue in self.cues:
            cue.validate()
            if cue.item_id in item_ids:
                raise ValueError(f"ID audio bị trùng: {cue.item_id}")
            item_ids.add(cue.item_id)

    def generation_spec(self, cue: EditorSpeechCueSpec, root_dir: Path) -> StudioGenerationSpec:
        return StudioGenerationSpec(
            project_id=self.project_id,
            title=cue.item_id,
            text=cue.text,
            engine_id=self.engine_id,
            language=cue.language or self.language,
            output_dir=str(root_dir),
            output_name=cue.item_id,
            model_id=self.model_id,
            device=self.device,
            speed=self.speed,
            formats=("wav",),
            voice=self.voice,
            engine_options=dict(self.engine_options),
        )


@dataclass(frozen=True)
class EditorSpeechItemResult:
    item_id: str
    track_id: str
    cue_id: str
    start_ms: int
    status: str
    wav_path: str = ""
    error: str = ""
    warnings: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["wav_path"] = self.wav_path or None
        payload["error"] = self.error or None
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class EditorSpeechResult:
    job_id: str
    project_id: str
    root_dir: str
    items: tuple[EditorSpeechItemResult, ...]

    @property
    def completed_count(self) -> int:
        return sum(item.status == "done" for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.status == "failed" for item in self.items)

    @property
    def status(self) -> str:
        if self.completed_count == len(self.items):
            return "completed"
        if self.completed_count:
            return "partial"
        return "failed"

    def to_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "root_dir": self.root_dir,
            "status": self.status,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "total_count": len(self.items),
            "items": [item.to_payload() for item in self.items],
        }


class EditorSpeechService:
    def execute(
        self,
        spec: EditorSpeechSpec,
        engine: StudioEngine,
        *,
        progress: EditorSpeechProgress | None = None,
        checkpoint: EditorSpeechCheckpoint | None = None,
        control: EditorSpeechControl | None = None,
        stop_event: threading.Event | None = None,
        item_finished: EditorSpeechItemCallback | None = None,
    ) -> EditorSpeechResult:
        spec.validate()
        if engine.engine_id != spec.engine_id:
            raise ValueError(f"Adapter {engine.engine_id} không xử lý được {spec.engine_id}.")

        root = unique_project_dir(Path(spec.output_dir).expanduser(), spec.title, "editor-speech")
        results: list[EditorSpeechItemResult] = []
        total = len(spec.cues)

        for index, cue in enumerate(spec.cues):
            if control:
                control()
            if stop_event is not None and stop_event.is_set():
                raise TaskCancelledError()
            if progress:
                progress(f"Đang tạo giọng {index + 1}/{total}", index / total)

            try:
                generation_spec = spec.generation_spec(cue, root)
                generation_spec.validate()
                artifact = engine.generate(
                    generation_spec,
                    lambda message: progress(message, index / total) if progress else None,
                )
                wav_path = artifact.wav_path.resolve()
                if not wav_path.is_relative_to(root.resolve()) or not wav_path.is_file():
                    raise ValueError("Engine trả về audio nằm ngoài thư mục của editor speech job.")
                item = EditorSpeechItemResult(
                    item_id=cue.item_id,
                    track_id=cue.track_id,
                    cue_id=cue.cue_id,
                    start_ms=cue.start_ms,
                    status="done",
                    wav_path=str(wav_path),
                    warnings=artifact.warnings,
                )
            except TaskCancelledError:
                raise
            except Exception as error:
                if stop_event is not None and stop_event.is_set():
                    raise TaskCancelledError() from error
                item = EditorSpeechItemResult(
                    item_id=cue.item_id,
                    track_id=cue.track_id,
                    cue_id=cue.cue_id,
                    start_ms=cue.start_ms,
                    status="failed",
                    error=str(error),
                )

            results.append(item)
            if item_finished:
                item_finished(item)
            completed = sum(result.status == "done" for result in results)
            failed = sum(result.status == "failed" for result in results)
            if checkpoint:
                checkpoint(
                    {
                        "job_id": spec.job_id,
                        "last_item_id": cue.item_id,
                        "completed": completed,
                        "failed": failed,
                        "total": total,
                    }
                )

        result = EditorSpeechResult(spec.job_id, spec.project_id, str(root.resolve()), tuple(results))
        if progress:
            progress(
                f"Tạo giọng hoàn tất: {result.completed_count} thành công, {result.failed_count} lỗi.",
                1.0,
            )
        return result
