from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .audio import concatenate_wavs, try_convert_to_mp3
from ..common.errors import TaskCancelledError
from ..common.paths import unique_project_dir
from .srt import SubtitleCue, render_srt
from .text_splitter import split_text
from .tts import EdgeTTS, TTSEngine

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class GenerationOptions:
    text: str
    output_dir: Path
    project_name: str = ""
    voice_name: str | None = None
    rate: int = 0
    volume: int = 100
    pause_ms: int = 250
    max_chars: int = 160
    export_mp3: bool = True
    keep_segments: bool = True


@dataclass(frozen=True)
class GenerationResult:
    project_dir: Path
    wav_path: Path
    srt_path: Path
    mp3_path: Path | None
    manifest_path: Path
    cue_count: int
    total_duration_ms: int
    warnings: list[str]


def generate_package(
    options: GenerationOptions,
    tts: TTSEngine | None = None,
    progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
) -> GenerationResult:
    report = progress or (lambda _message: None)
    chunks = split_text(options.text, max_chars=options.max_chars)
    if not chunks:
        raise ValueError("Script is empty.")

    tts_engine = tts or EdgeTTS()
    if not tts_engine.available():
        raise RuntimeError(tts_engine.unavailable_reason() or f"{tts_engine.label} is unavailable.")

    project_dir = unique_project_dir(options.output_dir, options.project_name)
    segments_dir = project_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    report(f"Preparing {len(chunks)} narration segments...")
    segment_paths: list[Path] = []

    try:
        for index, chunk in enumerate(chunks, start=1):
            if stop_event is not None and stop_event.is_set():
                raise TaskCancelledError()
            report(f"Synthesizing segment {index}/{len(chunks)}")
            segment_path = segments_dir / f"segment_{index:03}.wav"
            try:
                tts_engine.synthesize_to_wav(
                    chunk,
                    segment_path,
                    voice_name=options.voice_name,
                    rate=options.rate,
                    volume=options.volume,
                )
            except Exception as error:
                preview = chunk if len(chunk) <= 80 else f"{chunk[:77]}..."
                raise RuntimeError(f"Segment {index}/{len(chunks)} failed ({preview!r}): {error}") from error
            segment_paths.append(segment_path)
    except Exception:
        # A failed or cancelled run must not leave a partial project behind.
        shutil.rmtree(project_dir, ignore_errors=True)
        raise

    project_slug = project_dir.name
    wav_path = project_dir / f"{project_slug}.wav"
    srt_path = project_dir / f"{project_slug}.srt"
    mp3_path = project_dir / f"{project_slug}.mp3"
    manifest_path = project_dir / "manifest.json"

    report("Combining audio and calculating subtitle timings...")
    timings = concatenate_wavs(segment_paths, wav_path, gap_ms=options.pause_ms)
    cues = [
        SubtitleCue(index=index, start_ms=timing.start_ms, end_ms=timing.end_ms, text=chunk)
        for index, (chunk, timing) in enumerate(zip(chunks, timings), start=1)
    ]
    srt_path.write_text(render_srt(cues), encoding="utf-8")

    warnings: list[str] = []
    exported_mp3_path: Path | None = None
    if options.export_mp3:
        report("Exporting MP3...")
        ok, message = try_convert_to_mp3(wav_path, mp3_path)
        if ok:
            exported_mp3_path = mp3_path
        else:
            warnings.append(message)

    total_duration_ms = timings[-1].end_ms if timings else 0
    manifest = {
        "app": "Galaxy AI Voice & Subtitle Studio",
        "version": "0.1.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "tts_engine": tts_engine.code,
        "voice_name": options.voice_name,
        "rate": options.rate,
        "volume": options.volume,
        "pause_ms": options.pause_ms,
        "max_chars": options.max_chars,
        "cue_count": len(cues),
        "total_duration_ms": total_duration_ms,
        "files": {
            "wav": str(wav_path.name),
            "srt": str(srt_path.name),
            "mp3": str(mp3_path.name) if exported_mp3_path else None,
        },
        "warnings": warnings,
        "segments": [
            {
                "index": cue.index,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "text": cue.text,
            }
            for cue in cues
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if not options.keep_segments:
        for path in segment_paths:
            path.unlink(missing_ok=True)
        try:
            segments_dir.rmdir()
        except OSError:
            pass

    report("Done.")
    return GenerationResult(
        project_dir=project_dir,
        wav_path=wav_path,
        srt_path=srt_path,
        mp3_path=exported_mp3_path,
        manifest_path=manifest_path,
        cue_count=len(cues),
        total_duration_ms=total_duration_ms,
        warnings=warnings,
    )
