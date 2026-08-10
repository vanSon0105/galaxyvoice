from __future__ import annotations

import subprocess
import wave
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Mapping

from ...common.cache import write_json_atomic
from ...common.ffmpeg import find_ffmpeg
from ...common.paths import unique_project_dir
from ...voice.audio import concatenate_wavs, try_convert_to_mp3
from ...voice.srt import SubtitleCue, render_srt
from ..models import AUTO_MODE, CLONE_MODE, OmniVoiceGenerationOptions, OmniVoiceResult
from ..profiles import VoiceProfile
from ..service import WorkerClient, generate_omnivoice_audio
from .longform import LongformPlan, LongformSpan, PAUSE_SPAN, SPEECH_SPAN


WorkspaceProgress = Callable[[str], None]


@dataclass(frozen=True)
class LongformWorkspaceResult:
    project_dir: Path
    wav_path: Path
    srt_path: Path
    manifest_path: Path
    item_results: tuple[OmniVoiceResult, ...]
    mp3_path: Path | None = None
    m4b_path: Path | None = None
    warnings: tuple[str, ...] = ()

    @property
    def preview_path(self) -> Path:
        return self.wav_path


def render_longform_plan(
    base_options: OmniVoiceGenerationOptions,
    plan: LongformPlan,
    client: WorkerClient,
    *,
    profiles: tuple[VoiceProfile, ...] = (),
    cast_map: Mapping[str, str] | None = None,
    gap_ms: int = 250,
    export_mp3: bool = True,
    export_m4b: bool = False,
    title: str = "",
    author: str = "",
    progress: WorkspaceProgress | None = None,
) -> LongformWorkspaceResult:
    report = progress or (lambda _message: None)
    speech_spans = [span for span in plan.spans if span.kind == SPEECH_SPAN]
    if not speech_spans:
        raise ValueError("Kế hoạch không có đoạn thoại nào.")

    project_dir = unique_project_dir(
        base_options.output_dir,
        base_options.project_name,
        "omnivoice-longform",
    )
    resolved_cast = _profile_lookup(profiles, cast_map or {})
    item_results: list[OmniVoiceResult] = []
    speech_paths: dict[int, Path] = {}
    speech_total = len(speech_spans)
    speech_index = 0
    for span_index, span in enumerate(plan.spans):
        if span.kind != SPEECH_SPAN:
            continue
        speech_index += 1
        report(f"Đang tạo đoạn {speech_index}/{speech_total}: {span.voice_name or 'Auto'}")
        profile_id = resolved_cast.get(span.voice_name.casefold(), "") if span.voice_name else ""
        if not profile_id:
            profile_id = base_options.profile_id
        mode = CLONE_MODE if profile_id else AUTO_MODE
        options = replace(
            base_options,
            mode=mode,
            text=span.text,
            output_dir=project_dir,
            project_name=f"part-{speech_index:04d}",
            profile_id=profile_id,
            reference_audio=None if profile_id else base_options.reference_audio,
            save_profile_name="",
            instruct=base_options.instruct if mode == CLONE_MODE else "",
            speed=max(0.5, min(1.5, base_options.speed * span.speed)),
            duration=span.duration,
            export_mp3=False,
        )
        result = generate_omnivoice_audio(options, client, progress=report)
        if span.duration is not None:
            _fit_wav_duration(result.wav_path, round(span.duration * 1000))
        item_results.append(result)
        speech_paths[span_index] = result.wav_path

    with wave.open(str(item_results[0].wav_path), "rb") as first:
        params = first.getparams()

    sequence_paths: list[Path] = []
    sequence_spans: list[LongformSpan | None] = []
    pauses_dir = project_dir / "pauses"
    pause_index = 0
    previous_was_speech = False
    for span_index, span in enumerate(plan.spans):
        if span.kind == SPEECH_SPAN:
            if previous_was_speech and gap_ms > 0:
                pause_index += 1
                pause_path = pauses_dir / f"gap-{pause_index:04d}.wav"
                _write_silence(pause_path, params, gap_ms)
                sequence_paths.append(pause_path)
                sequence_spans.append(None)
            sequence_paths.append(speech_paths[span_index])
            sequence_spans.append(span)
            previous_was_speech = True
        elif span.kind == PAUSE_SPAN and span.pause_ms > 0:
            pause_index += 1
            pause_path = pauses_dir / f"pause-{pause_index:04d}.wav"
            _write_silence(pause_path, params, span.pause_ms)
            sequence_paths.append(pause_path)
            sequence_spans.append(span)
            previous_was_speech = False

    wav_path = project_dir / "combined.wav"
    timings = concatenate_wavs(sequence_paths, wav_path, gap_ms=0)
    cues: list[SubtitleCue] = []
    chapter_bounds: dict[str, list[int]] = {}
    for span, timing in zip(sequence_spans, timings):
        if span is None:
            continue
        if span.chapter:
            bounds = chapter_bounds.setdefault(span.chapter, [timing.start_ms, timing.end_ms])
            bounds[0] = min(bounds[0], timing.start_ms)
            bounds[1] = max(bounds[1], timing.end_ms)
        if span.kind == SPEECH_SPAN:
            cues.append(
                SubtitleCue(
                    index=span.source_index or len(cues) + 1,
                    start_ms=timing.start_ms,
                    end_ms=timing.end_ms,
                    text=span.text,
                )
            )
    srt_path = project_dir / "combined.srt"
    srt_path.write_text(render_srt(cues), encoding="utf-8")

    warnings: list[str] = [warning for item in item_results for warning in item.warnings]
    mp3_path: Path | None = None
    if export_mp3:
        candidate = project_dir / "combined.mp3"
        converted, message = try_convert_to_mp3(wav_path, candidate)
        if converted:
            mp3_path = candidate
        else:
            warnings.append(message)

    m4b_path: Path | None = None
    if export_m4b:
        candidate = project_dir / "audiobook.m4b"
        converted, message = _convert_to_m4b(
            wav_path,
            candidate,
            title=title or base_options.project_name,
            author=author,
            chapters=[
                (chapter, *chapter_bounds[chapter])
                for chapter in plan.chapters
                if chapter in chapter_bounds
            ],
        )
        if converted:
            m4b_path = candidate
        else:
            warnings.append(message)

    manifest_path = project_dir / "workspace_manifest.json"
    write_json_atomic(
        manifest_path,
        {
            "version": 1,
            "engine": "omnivoice-workspace",
            "title": title,
            "author": author,
            "options": {
                "model_id": base_options.model_id,
                "device": base_options.device,
                "language": base_options.language,
                "gap_ms": max(0, int(gap_ms)),
            },
            "chapters": [
                {"title": chapter, "start_ms": start_ms, "end_ms": end_ms}
                for chapter, start_ms, end_ms in (
                    (chapter, *chapter_bounds[chapter])
                    for chapter in plan.chapters
                    if chapter in chapter_bounds
                )
            ],
            "spans": [asdict(span) for span in plan.spans],
            "files": {
                "wav": str(wav_path),
                "srt": str(srt_path),
                "mp3": str(mp3_path) if mp3_path else None,
                "m4b": str(m4b_path) if m4b_path else None,
            },
            "warnings": warnings,
        },
    )
    return LongformWorkspaceResult(
        project_dir=project_dir,
        wav_path=wav_path,
        srt_path=srt_path,
        manifest_path=manifest_path,
        item_results=tuple(item_results),
        mp3_path=mp3_path,
        m4b_path=m4b_path,
        warnings=tuple(warnings),
    )


def _profile_lookup(
    profiles: tuple[VoiceProfile, ...],
    cast_map: Mapping[str, str],
) -> dict[str, str]:
    lookup = {key.casefold(): value for key, value in cast_map.items() if value}
    for profile in profiles:
        lookup.setdefault(profile.profile_id.casefold(), profile.profile_id)
        lookup.setdefault(profile.display_name.casefold(), profile.profile_id)
    return lookup


def _fit_wav_duration(path: Path, target_ms: int) -> None:
    with wave.open(str(path), "rb") as source:
        params = source.getparams()
        frames = source.readframes(source.getnframes())
    target_frames = max(1, round(params.framerate * max(1, target_ms) / 1000))
    frame_size = params.nchannels * params.sampwidth
    target_bytes = target_frames * frame_size
    fitted = frames[:target_bytes].ljust(target_bytes, b"\x00")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with wave.open(str(temporary), "wb") as output:
        output.setparams(params)
        output.writeframes(fitted)
    temporary.replace(path)


def _write_silence(path: Path, params: wave._wave_params, duration_ms: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, round(params.framerate * max(1, duration_ms) / 1000))
    with wave.open(str(path), "wb") as output:
        output.setparams(params)
        output.writeframes(b"\x00" * frames * params.nchannels * params.sampwidth)


def _convert_to_m4b(
    wav_path: Path,
    output_path: Path,
    *,
    title: str,
    author: str,
    chapters: list[tuple[str, int, int]],
) -> tuple[bool, str]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "Không tìm thấy ffmpeg; đã bỏ qua M4B."
    metadata_path = output_path.with_suffix(".ffmetadata")
    lines = [";FFMETADATA1", f"title={_escape_metadata(title)}"]
    if author.strip():
        lines.append(f"artist={_escape_metadata(author)}")
    for chapter, start_ms, end_ms in chapters:
        lines.extend(
            (
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={max(0, start_ms)}",
                f"END={max(start_ms + 1, end_ms)}",
                f"title={_escape_metadata(chapter)}",
            )
        )
    metadata_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(wav_path),
        "-i",
        str(metadata_path),
        "-map_metadata",
        "1",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    finally:
        metadata_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        return False, completed.stderr.strip() or "ffmpeg không tạo được M4B."
    return True, "M4B exported."


def _escape_metadata(value: str) -> str:
    return value.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", " ")
