from __future__ import annotations

import shutil
import subprocess
import wave
from array import array
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Callable, Mapping

from ...common.cache import read_json, stable_digest, write_json_atomic
from ...common.errors import TaskCancelledError
from ...common.ffmpeg import find_ffmpeg
from ...common.paths import slugify, unique_project_dir
from ...voice.audio import concatenate_wavs
from ...voice.media import _run_command, _run_ffmpeg
from ...voice.srt import SubtitleCue, render_srt
from ..models import AUTO_MODE, CLONE_MODE, OmniVoiceGenerationOptions, OmniVoiceResult
from ..profiles import VoiceProfile
from ..service import WorkerClient, generate_omnivoice_audio
from .longform import LongformPlan, LongformSpan, PAUSE_SPAN, SPEECH_SPAN
from .dubbing.model import DubbingFitPolicy, DubbingSegmentMeasurement


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
    stems_dir: Path | None = None
    warnings: tuple[str, ...] = ()
    fit_measurements: tuple[DubbingSegmentMeasurement, ...] = ()
    quality_report_path: Path | None = None
    mixed_audio_path: Path | None = None
    video_path: Path | None = None

    @property
    def preview_path(self) -> Path:
        return self.wav_path


@dataclass(frozen=True)
class ResumableWorkspaceJob:
    project_dir: Path
    project_name: str
    status: str
    completed_spans: int
    total_spans: int
    updated_at: str
    error: str = ""


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
    export_stems: bool = False,
    mastering: bool = False,
    target_lufs: float = -16.0,
    true_peak_db: float = -1.0,
    title: str = "",
    author: str = "",
    cover_path: Path | None = None,
    project_document: Mapping[str, object] | None = None,
    progress: WorkspaceProgress | None = None,
    resume_project_dir: Path | None = None,
    stop_event: threading.Event | None = None,
    smart_fit: bool = False,
    fit_policy: DubbingFitPolicy | None = None,
) -> LongformWorkspaceResult:
    report = progress or (lambda _message: None)
    speech_spans = [span for span in plan.spans if span.kind == SPEECH_SPAN]
    if not speech_spans:
        raise ValueError("Kế hoạch không có đoạn thoại nào.")
    markup_errors = [issue.message for issue in plan.issues if issue.severity == "error"]
    if markup_errors:
        raise ValueError("Markup biểu cảm chưa hợp lệ: " + "; ".join(markup_errors))

    project_dir = (
        _validated_resume_dir(base_options.output_dir, resume_project_dir)
        if resume_project_dir is not None
        else unique_project_dir(
            base_options.output_dir,
            base_options.project_name,
            "omnivoice-longform",
        )
    )
    resolved_cast = _profile_lookup(profiles, cast_map or {})
    job_path = project_dir / "workspace_job.json"
    used_cast = {
        span.voice_name.casefold(): resolved_cast.get(span.voice_name.casefold(), "")
        for span in plan.spans
        if span.voice_name and not span.profile_id
    }
    resolved_fit_policy = fit_policy or DubbingFitPolicy()
    plan_signature = _plan_signature(
        base_options,
        plan,
        used_cast,
        gap_ms,
        smart_fit=smart_fit,
        fit_policy=resolved_fit_policy,
    )
    job = _load_or_create_job(
        job_path,
        project_name=base_options.project_name,
        signature=plan_signature,
        total_spans=len(speech_spans),
    )
    cached_items = job.get("items") if isinstance(job.get("items"), dict) else {}
    job["status"] = "running"
    job["error"] = ""
    _save_job(job_path, job)
    item_results: list[OmniVoiceResult] = []
    speech_paths: dict[int, Path] = {}
    speech_total = len(speech_spans)
    speech_index = 0
    fit_measurements: list[DubbingSegmentMeasurement] = []
    try:
        for span_index, span in enumerate(plan.spans):
            if span.kind != SPEECH_SPAN:
                continue
            if stop_event is not None and stop_event.is_set():
                raise TaskCancelledError()
            speech_index += 1
            profile_id = span.profile_id
            if not profile_id and span.voice_name:
                profile_id = resolved_cast.get(span.voice_name.casefold(), "")
            if not profile_id:
                profile_id = base_options.profile_id
            item_key = str(span_index)
            item_signature = _span_signature(base_options, span, profile_id)
            cached = cached_items.get(item_key) if isinstance(cached_items, dict) else None
            reused = _cached_result(cached, item_signature)
            if reused is not None:
                report(f"Dùng lại đoạn {speech_index}/{speech_total}: {span.voice_name or 'Auto'}")
                result = reused
                cached_measurement = _cached_measurement(cached)
                if cached_measurement is not None:
                    fit_measurements.append(cached_measurement)
            else:
                report(f"Đang tạo đoạn {speech_index}/{speech_total}: {span.voice_name or 'Auto'}")
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
                    instruct=span.instruction or base_options.instruct,
                    speed=max(0.5, min(1.5, base_options.speed * span.speed)),
                    duration=span.duration,
                    export_mp3=False,
                )
                result = generate_omnivoice_audio(options, client, progress=report)
                measurement: DubbingSegmentMeasurement | None = None
                if span.duration is not None:
                    target_ms = round(span.duration * 1000)
                    if smart_fit:
                        measurement = _smart_fit_wav_duration(
                            result.wav_path,
                            target_ms,
                            segment_id=span.segment_id or str(span.source_index or speech_index),
                            policy=resolved_fit_policy,
                            stop_event=stop_event,
                        )
                    else:
                        _fit_wav_duration(result.wav_path, target_ms)
                if abs(span.volume - 1.0) > 0.001:
                    _scale_wav_volume(result.wav_path, span.volume)
                cached_items[item_key] = {
                    "signature": item_signature,
                    "project_dir": str(result.project_dir),
                    "wav_path": str(result.wav_path),
                    "manifest_path": str(result.manifest_path),
                    "warnings": list(result.warnings),
                    "fit_measurement": asdict(measurement) if measurement is not None else None,
                }
                if measurement is not None:
                    fit_measurements.append(measurement)
                job["items"] = cached_items
                job["completed_spans"] = len(cached_items)
                _save_job(job_path, job)
            item_results.append(result)
            speech_paths[span_index] = result.wav_path
    except Exception as error:
        job["status"] = "failed"
        job["error"] = str(error)
        job["completed_spans"] = len(cached_items)
        _save_job(job_path, job)
        raise

    with wave.open(str(item_results[0].wav_path), "rb") as first:
        params = first.getparams()

    stems_dir: Path | None = None
    if export_stems:
        stems_dir = project_dir / "stems"
        stems_dir.mkdir(parents=True, exist_ok=True)
        for index, (span, result) in enumerate(zip(speech_spans, item_results), start=1):
            label = slugify("-".join(part for part in (span.chapter, span.voice_name) if part))
            destination = stems_dir / f"{index:04d}-{label or 'voice'}.wav"
            shutil.copy2(result.wav_path, destination)

    sequence_paths: list[Path] = []
    sequence_spans: list[LongformSpan | None] = []
    pauses_dir = project_dir / "pauses"
    pause_index = 0
    previous_was_speech = False
    previous_source_index: int | None = None
    for span_index, span in enumerate(plan.spans):
        if span.kind == SPEECH_SPAN:
            same_source_line = (
                span.source_index is not None
                and span.source_index == previous_source_index
            )
            if previous_was_speech and gap_ms > 0 and not same_source_line:
                pause_index += 1
                pause_path = pauses_dir / f"gap-{pause_index:04d}.wav"
                _write_silence(pause_path, params, gap_ms)
                sequence_paths.append(pause_path)
                sequence_spans.append(None)
            sequence_paths.append(speech_paths[span_index])
            sequence_spans.append(span)
            previous_was_speech = True
            previous_source_index = span.source_index
        elif span.kind == PAUSE_SPAN and span.pause_ms > 0:
            pause_index += 1
            pause_path = pauses_dir / f"pause-{pause_index:04d}.wav"
            _write_silence(pause_path, params, span.pause_ms)
            sequence_paths.append(pause_path)
            sequence_spans.append(span)
            previous_was_speech = False
            previous_source_index = span.source_index

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
                    index=len(cues) + 1,
                    start_ms=timing.start_ms,
                    end_ms=timing.end_ms,
                    text=span.display_text or span.text,
                )
            )
    srt_path = project_dir / "combined.srt"
    srt_path.write_text(render_srt(cues), encoding="utf-8")

    warnings: list[str] = [
        issue.message for issue in plan.issues if issue.severity != "error"
    ]
    warnings.extend(warning for item in item_results for warning in item.warnings)
    if mastering:
        report("Đang cân bằng âm lượng bản hoàn chỉnh...")
        mastered, message = _master_longform_wav(
            wav_path,
            target_lufs=target_lufs,
            true_peak_db=true_peak_db,
            stop_event=stop_event,
        )
        if not mastered:
            warnings.append(message)
    mp3_path: Path | None = None
    if export_mp3:
        candidate = project_dir / "combined.mp3"
        converted, message = _convert_to_mp3(
            wav_path,
            candidate,
            title=title or base_options.project_name,
            author=author,
            cover_path=cover_path,
        )
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
            cover_path=cover_path,
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
                "mastering": bool(mastering),
                "target_lufs": _clamp_target_lufs(target_lufs),
                "true_peak_db": _clamp_true_peak(true_peak_db),
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
            "expressive_issues": [asdict(issue) for issue in plan.issues],
            "document": _manifest_document(project_document),
            "files": {
                "wav": str(wav_path),
                "srt": str(srt_path),
                "mp3": str(mp3_path) if mp3_path else None,
                "m4b": str(m4b_path) if m4b_path else None,
                "stems": str(stems_dir) if stems_dir else None,
            },
            "warnings": warnings,
            "fit_measurements": [asdict(item) for item in fit_measurements],
        },
    )
    job["status"] = "completed"
    job["error"] = ""
    job["completed_spans"] = speech_total
    job["files"] = {
        "wav": str(wav_path),
        "srt": str(srt_path),
        "mp3": str(mp3_path) if mp3_path else "",
        "m4b": str(m4b_path) if m4b_path else "",
    }
    _save_job(job_path, job)
    return LongformWorkspaceResult(
        project_dir=project_dir,
        wav_path=wav_path,
        srt_path=srt_path,
        manifest_path=manifest_path,
        item_results=tuple(item_results),
        mp3_path=mp3_path,
        m4b_path=m4b_path,
        stems_dir=stems_dir,
        warnings=tuple(warnings),
        fit_measurements=tuple(fit_measurements),
    )


def find_resumable_workspace_jobs(output_dir: Path) -> tuple[ResumableWorkspaceJob, ...]:
    root = Path(output_dir).expanduser()
    if not root.is_dir():
        return ()
    jobs: list[ResumableWorkspaceJob] = []
    for path in root.glob("*/workspace_job.json"):
        payload = read_json(path)
        if not isinstance(payload, dict) or payload.get("status") not in {"running", "failed"}:
            continue
        jobs.append(
            ResumableWorkspaceJob(
                project_dir=path.parent,
                project_name=str(payload.get("project_name") or path.parent.name),
                status=str(payload.get("status") or "failed"),
                completed_spans=max(0, int(payload.get("completed_spans") or 0)),
                total_spans=max(0, int(payload.get("total_spans") or 0)),
                updated_at=str(payload.get("updated_at") or ""),
                error=str(payload.get("error") or ""),
            )
        )
    return tuple(sorted(jobs, key=lambda item: item.updated_at, reverse=True))


def _validated_resume_dir(output_dir: Path, resume_project_dir: Path) -> Path:
    root = Path(output_dir).expanduser().resolve()
    candidate = Path(resume_project_dir).expanduser().resolve()
    if candidate.parent != root or not candidate.is_dir():
        raise ValueError("Thư mục resume phải là project nằm trực tiếp trong output OmniVoice.")
    return candidate


def _plan_signature(
    options: OmniVoiceGenerationOptions,
    plan: LongformPlan,
    cast_map: Mapping[str, str],
    gap_ms: int,
    *,
    smart_fit: bool = False,
    fit_policy: DubbingFitPolicy | None = None,
) -> str:
    return stable_digest(
        {
            "model_id": options.model_id,
            "device": options.device,
            "language": options.language,
            "base_profile": options.profile_id,
            "speed": options.speed,
            "gap_ms": max(0, int(gap_ms)),
            "cast": dict(sorted(cast_map.items())),
            "spans": [asdict(span) for span in plan.spans],
            "smart_fit": smart_fit,
            "fit_policy": asdict(fit_policy or DubbingFitPolicy()),
        }
    )


def _span_signature(
    options: OmniVoiceGenerationOptions,
    span: LongformSpan,
    profile_id: str,
) -> str:
    return stable_digest(
        {
            "model_id": options.model_id,
            "language": options.language,
            "profile_id": profile_id,
            "base_speed": options.speed,
            "num_step": options.num_step,
            "guidance_scale": options.guidance_scale,
            "span": asdict(span),
        }
    )


def _load_or_create_job(
    path: Path,
    *,
    project_name: str,
    signature: str,
    total_spans: int,
) -> dict[str, object]:
    existing = read_json(path)
    if isinstance(existing, dict):
        if existing.get("signature") != signature:
            raise ValueError("Project resume không còn khớp với script hoặc thiết lập hiện tại.")
        return existing
    return {
        "version": 1,
        "project_name": project_name,
        "signature": signature,
        "status": "pending",
        "completed_spans": 0,
        "total_spans": max(0, int(total_spans)),
        "items": {},
        "error": "",
    }


def _save_job(path: Path, payload: dict[str, object]) -> None:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(path, payload)


def _cached_result(payload: object, signature: str) -> OmniVoiceResult | None:
    if not isinstance(payload, dict) or payload.get("signature") != signature:
        return None
    wav_path = Path(str(payload.get("wav_path") or ""))
    project_dir = Path(str(payload.get("project_dir") or ""))
    manifest_path = Path(str(payload.get("manifest_path") or ""))
    if not wav_path.is_file() or not project_dir.is_dir():
        return None
    warnings = payload.get("warnings")
    return OmniVoiceResult(
        project_dir=project_dir,
        wav_path=wav_path,
        mp3_path=None,
        manifest_path=manifest_path,
        warnings=tuple(str(item) for item in warnings) if isinstance(warnings, list) else (),
    )


def _cached_measurement(payload: object) -> DubbingSegmentMeasurement | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("fit_measurement"), dict):
        return None
    try:
        return DubbingSegmentMeasurement(**payload["fit_measurement"])
    except (TypeError, ValueError):
        return None


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


def _wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as source:
        return max(1, round(source.getnframes() * 1000 / source.getframerate()))


def _smart_fit_wav_duration(
    path: Path,
    target_ms: int,
    *,
    segment_id: str,
    policy: DubbingFitPolicy,
    stop_event: threading.Event | None = None,
) -> DubbingSegmentMeasurement:
    """Fit speech to a cue with bounded FFmpeg atempo, then exact pad/trim."""

    target = max(1, int(target_ms))
    raw_duration = _wav_duration_ms(path)
    required_tempo = raw_duration / target
    tempo = max(policy.min_tempo, min(policy.max_tempo, required_tempo))
    method = "exact-pad-trim"
    tempo_duration = raw_duration
    ffmpeg = find_ffmpeg()
    if ffmpeg and abs(tempo - 1.0) > 0.005:
        temporary = path.with_suffix(".smart-fit.wav")
        try:
            _run_ffmpeg(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(path),
                    "-filter:a",
                    f"atempo={tempo:.6f}",
                    str(temporary),
                ],
                _run_command,
                stop_event=stop_event,
            )
        except TaskCancelledError:
            temporary.unlink(missing_ok=True)
            raise
        except RuntimeError:
            temporary.unlink(missing_ok=True)
        else:
            temporary.replace(path)
            tempo_duration = _wav_duration_ms(path)
            method = "ffmpeg-atempo"
    clipped_ms = max(0, tempo_duration - target)
    padded_ms = max(0, target - tempo_duration)
    _fit_wav_duration(path, target)
    return DubbingSegmentMeasurement(
        segment_id=segment_id,
        raw_duration_ms=raw_duration,
        tempo=round(tempo, 6),
        tempo_duration_ms=tempo_duration,
        fitted_duration_ms=_wav_duration_ms(path),
        method=method,
        clipped_ms=clipped_ms,
        padded_ms=padded_ms,
    )


def _scale_wav_volume(path: Path, volume: float) -> None:
    factor = max(0.0, min(2.0, float(volume)))
    with wave.open(str(path), "rb") as source:
        params = source.getparams()
        frames = source.readframes(source.getnframes())
    if params.sampwidth != 2:
        return
    samples = array("h")
    samples.frombytes(frames)
    for index, sample in enumerate(samples):
        samples[index] = max(-32768, min(32767, round(sample * factor)))
    temporary = path.with_suffix(path.suffix + ".tmp")
    with wave.open(str(temporary), "wb") as output:
        output.setparams(params)
        output.writeframes(samples.tobytes())
    temporary.replace(path)


def _write_silence(path: Path, params: wave._wave_params, duration_ms: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, round(params.framerate * max(1, duration_ms) / 1000))
    with wave.open(str(path), "wb") as output:
        output.setparams(params)
        output.writeframes(b"\x00" * frames * params.nchannels * params.sampwidth)


def _master_longform_wav(
    wav_path: Path,
    *,
    target_lufs: float,
    true_peak_db: float,
    stop_event: threading.Event | None = None,
) -> tuple[bool, str]:
    """Apply a conservative one-pass loudness master without risking the raw render."""

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "Không tìm thấy ffmpeg; đã giữ nguyên WAV chưa mastering."
    target = _clamp_target_lufs(target_lufs)
    peak = _clamp_true_peak(true_peak_db)
    temporary = wav_path.with_name(f"{wav_path.stem}.mastered.wav")
    try:
        _run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(wav_path),
                "-af",
                f"loudnorm=I={target:.1f}:TP={peak:.1f}:LRA=11",
                "-c:a",
                "pcm_s16le",
                str(temporary),
            ],
            _run_command,
            stop_event=stop_event,
        )
    except TaskCancelledError:
        temporary.unlink(missing_ok=True)
        raise
    except RuntimeError as error:
        temporary.unlink(missing_ok=True)
        return False, f"Mastering thất bại; đã giữ nguyên WAV: {error}"
    temporary.replace(wav_path)
    return True, "Mastering completed."


def _clamp_target_lufs(value: float) -> float:
    return max(-24.0, min(-9.0, float(value)))


def _clamp_true_peak(value: float) -> float:
    return max(-6.0, min(-0.1, float(value)))


def _convert_to_m4b(
    wav_path: Path,
    output_path: Path,
    *,
    title: str,
    author: str,
    cover_path: Path | None,
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
    ]
    valid_cover = cover_path is not None and Path(cover_path).is_file()
    if valid_cover:
        command.extend(("-i", str(cover_path)))
    command.extend(("-map_metadata", "1"))
    if valid_cover:
        command.extend(
            (
                "-map",
                "0:a:0",
                "-map",
                "2:v:0",
                "-c:v",
                "copy",
                "-disposition:v:0",
                "attached_pic",
            )
        )
    command.extend([
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    finally:
        metadata_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        return False, completed.stderr.strip() or "ffmpeg không tạo được M4B."
    return True, "M4B exported."


def _escape_metadata(value: str) -> str:
    return value.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", " ")


def _manifest_document(document: Mapping[str, object] | None) -> dict[str, object]:
    if not document:
        return {}
    items = document.get("items")
    cleaned_items = []
    if isinstance(items, list):
        cleaned_items = [
            {key: value for key, value in item.items() if key != "preview_path"}
            for item in items
            if isinstance(item, dict)
        ]
    return {
        "chapters": list(document.get("chapters") or []),
        "language": str(document.get("language") or "auto"),
        "items": cleaned_items,
        "pronunciation_rules": list(document.get("pronunciation_rules") or []),
    }


def _convert_to_mp3(
    wav_path: Path,
    output_path: Path,
    *,
    title: str,
    author: str,
    cover_path: Path | None,
) -> tuple[bool, str]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "Khong tim thay ffmpeg; da bo qua MP3."
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav_path)]
    valid_cover = cover_path is not None and Path(cover_path).is_file()
    if valid_cover:
        command.extend(("-i", str(cover_path), "-map", "0:a:0", "-map", "1:v:0"))
    command.extend(("-c:a", "libmp3lame", "-q:a", "2", "-id3v2_version", "3"))
    if title.strip():
        command.extend(("-metadata", f"title={title.strip()}"))
    if author.strip():
        command.extend(("-metadata", f"artist={author.strip()}"))
    if valid_cover:
        command.extend(
            (
                "-c:v",
                "mjpeg",
                "-disposition:v:0",
                "attached_pic",
                "-metadata:s:v",
                "title=Cover",
                "-metadata:s:v",
                "comment=Cover (front)",
            )
        )
    command.append(str(output_path))
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return False, completed.stderr.strip() or "ffmpeg khong tao duoc MP3."
    return True, "MP3 exported."
