from __future__ import annotations

from collections import Counter
import json
import math
import re
import threading
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable

from ..common.cache import write_json_atomic
from ..common.errors import TaskCancelledError
from ..common.paths import slugify, unique_project_dir
from ..voice.audio import concatenate_wavs, try_convert_to_mp3
from .models import OmniVoiceGenerationOptions, OmniVoiceResult
from .service import WorkerClient, generate_omnivoice_audio


BatchProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class OmniVoiceBatchItem:
    item_id: str
    text: str
    language: str = ""
    speed: float | None = None
    duration: float | None = None


@dataclass(frozen=True)
class OmniVoiceBatchResult:
    project_dir: Path
    manifest_path: Path
    item_results: tuple[OmniVoiceResult, ...]
    combined_wav_path: Path | None = None
    combined_mp3_path: Path | None = None
    warnings: tuple[str, ...] = ()

    @property
    def preview_path(self) -> Path | None:
        if self.combined_wav_path is not None:
            return self.combined_wav_path
        if self.item_results:
            return self.item_results[0].wav_path
        return None


def parse_batch_items(source: str) -> tuple[OmniVoiceBatchItem, ...]:
    items: list[OmniVoiceBatchItem] = []
    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"JSONL dòng {line_number} không hợp lệ: {error.msg}") from error
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL dòng {line_number} phải là một object.")
            text = str(payload.get("text") or "").strip()
            item_id = str(payload.get("id") or f"voice-{line_number:03d}").strip()
            language = str(payload.get("language_id") or payload.get("language") or "").strip()
            speed = _optional_positive_float(payload.get("speed"), "speed", line_number)
            duration = _optional_positive_float(payload.get("duration"), "duration", line_number)
        else:
            text = line
            item_id = f"voice-{line_number:03d}"
            language = ""
            speed = None
            duration = None
        if not text:
            raise ValueError(f"JSONL dòng {line_number} thiếu nội dung text.")
        items.append(
            OmniVoiceBatchItem(
                item_id=slugify(item_id),
                text=text,
                language=language,
                speed=speed,
                duration=duration,
            )
        )
    if not items:
        raise ValueError("Hãy nhập ít nhất một câu hoặc một dòng JSONL.")
    duplicates = sorted(
        item_id
        for item_id, count in Counter(item.item_id for item in items).items()
        if count > 1
    )
    if duplicates:
        raise ValueError(f"ID batch bị trùng: {', '.join(duplicates)}")
    return tuple(items)


def split_long_form(source: str) -> tuple[OmniVoiceBatchItem, ...]:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n(?:[ \t]*\n)+", normalized)
    ]
    paragraphs = [paragraph.replace("\n", " ") for paragraph in paragraphs if paragraph]
    if not paragraphs:
        raise ValueError("Hãy nhập nội dung long-form.")
    return tuple(
        OmniVoiceBatchItem(item_id=f"part-{index:03d}", text=text)
        for index, text in enumerate(paragraphs, start=1)
    )


def generate_omnivoice_batch(
    base_options: OmniVoiceGenerationOptions,
    items: tuple[OmniVoiceBatchItem, ...],
    client: WorkerClient,
    *,
    combine: bool = False,
    gap_ms: int = 250,
    progress: BatchProgressCallback | None = None,
    stop_event: threading.Event | None = None,
) -> OmniVoiceBatchResult:
    if not items:
        raise ValueError("Batch Voice không có mục nào để xử lý.")

    project_dir = unique_project_dir(
        base_options.output_dir,
        base_options.project_name,
        "omnivoice-batch",
    )
    manifest_path = project_dir / "manifest.json"
    item_results: list[OmniVoiceResult] = []
    warnings: list[str] = []

    for index, item in enumerate(items, start=1):
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelledError()
        if progress is not None:
            progress(f"Đang tạo {index}/{len(items)}: {item.item_id}")
        item_options = replace(
            base_options,
            text=item.text,
            output_dir=project_dir,
            project_name=item.item_id,
            language=item.language or base_options.language,
            speed=item.speed if item.speed is not None else base_options.speed,
            duration=item.duration if item.duration is not None else base_options.duration,
            save_profile_name="",
            export_mp3=base_options.export_mp3 and not combine,
        )
        result = generate_omnivoice_audio(item_options, client, progress=progress)
        item_results.append(result)
        warnings.extend(result.warnings)
        _write_batch_manifest(
            manifest_path,
            base_options,
            items,
            item_results,
            combine=combine,
            gap_ms=gap_ms,
            completed=False,
            combined_wav_path=None,
            combined_mp3_path=None,
            warnings=warnings,
        )

    combined_wav_path: Path | None = None
    combined_mp3_path: Path | None = None
    if combine:
        if progress is not None:
            progress("Đang ghép các phần long-form...")
        combined_wav_path = project_dir / "combined.wav"
        concatenate_wavs(
            [result.wav_path for result in item_results],
            combined_wav_path,
            gap_ms=max(0, int(gap_ms)),
        )
        if base_options.export_mp3:
            candidate = project_dir / "combined.mp3"
            converted, message = try_convert_to_mp3(combined_wav_path, candidate)
            if converted:
                combined_mp3_path = candidate
            else:
                warnings.append(message)

    _write_batch_manifest(
        manifest_path,
        base_options,
        items,
        item_results,
        combine=combine,
        gap_ms=gap_ms,
        completed=True,
        combined_wav_path=combined_wav_path,
        combined_mp3_path=combined_mp3_path,
        warnings=warnings,
    )
    return OmniVoiceBatchResult(
        project_dir=project_dir,
        manifest_path=manifest_path,
        item_results=tuple(item_results),
        combined_wav_path=combined_wav_path,
        combined_mp3_path=combined_mp3_path,
        warnings=tuple(warnings),
    )


def _write_batch_manifest(
    path: Path,
    options: OmniVoiceGenerationOptions,
    items: tuple[OmniVoiceBatchItem, ...],
    results: list[OmniVoiceResult],
    *,
    combine: bool,
    gap_ms: int,
    completed: bool,
    combined_wav_path: Path | None,
    combined_mp3_path: Path | None,
    warnings: list[str],
) -> None:
    result_by_id = {
        item.item_id: result
        for item, result in zip(items, results)
    }
    write_json_atomic(
        path,
        {
            "version": 1,
            "engine": "omnivoice-batch",
            "completed": completed,
            "mode": options.mode,
            "model_id": options.model_id,
            "device": options.device,
            "combine": combine,
            "gap_ms": max(0, int(gap_ms)),
            "combined_wav_path": str(combined_wav_path) if combined_wav_path else None,
            "combined_mp3_path": str(combined_mp3_path) if combined_mp3_path else None,
            "items": [
                {
                    **asdict(item),
                    "project_dir": (
                        str(result_by_id[item.item_id].project_dir)
                        if item.item_id in result_by_id
                        else None
                    ),
                    "wav_path": (
                        str(result_by_id[item.item_id].wav_path)
                        if item.item_id in result_by_id
                        else None
                    ),
                }
                for item in items
            ],
            "warnings": warnings,
        },
    )


def _optional_positive_float(value: object, field: str, line_number: int) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"JSONL dòng {line_number}: {field} phải là số.") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"JSONL dòng {line_number}: {field} phải lớn hơn 0.")
    return number
