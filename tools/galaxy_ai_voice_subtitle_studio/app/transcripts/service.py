from __future__ import annotations

import importlib.util
import os
import re
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from ..common.compute import AUTO_DEVICE, normalize_processing_device, resolve_whisper_runtime
from ..common.errors import TaskCancelledError
from ..common.ffmpeg import ffmpeg_missing_message, find_ffmpeg
from ..reliability.service import guard_output_space
from ..voice.media import _run_command, _run_ffmpeg, build_extract_wav_command
from ..voice.srt import SubtitleCue, format_timestamp, parse_srt, render_srt
from .models import (
    TranscriptCue,
    TranscriptProject,
    TranscriptSpeaker,
    TranscriptWord,
    normalize_cues,
    utc_now,
    validate_project,
)
from .repository import TranscriptRepository

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class SpeakerTurn:
    speaker_id: str
    start_ms: int
    end_ms: int


def available_diarization_devices() -> tuple[str, ...]:
    """Report devices exposed by the same PyTorch runtime pyannote will use."""

    devices = ["cpu"]
    try:
        import torch

        if torch.cuda.is_available():
            devices.insert(0, "cuda")
    except Exception:
        pass
    return tuple(devices)


def resolve_diarization_device(requested: str) -> str:
    devices = available_diarization_devices()
    normalized = normalize_processing_device(requested)
    if normalized == AUTO_DEVICE:
        return "cuda" if "cuda" in devices else "cpu"
    if normalized not in devices:
        raise RuntimeError(
            f"Pyannote không dùng được {normalized.upper()}; "
            f"thiết bị hiện có: {', '.join(devices).upper()}."
        )
    return normalized


def format_vtt_timestamp(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"


def render_vtt(
    cues: Sequence[TranscriptCue],
    speakers: Mapping[str, str] | None = None,
) -> str:
    speaker_map = speakers or {}
    blocks: list[str] = ["WEBVTT\n"]
    for cue in cues:
        end_ms = max(cue.end_ms, cue.start_ms + 1)
        blocks.append(
            f"{format_vtt_timestamp(cue.start_ms)} --> {format_vtt_timestamp(end_ms)}\n"
            f"<v {speaker_map.get(cue.speaker_id, cue.speaker_id)}>{cue.text.strip()}"
        )
    return "\n\n".join(blocks) + ("\n" if len(blocks) > 1 else "")


def render_transcript_srt(
    cues: Sequence[TranscriptCue],
    speakers: Mapping[str, str] | None = None,
) -> str:
    speaker_map = speakers or {}
    include_speakers = bool(speaker_map)
    subtitle_cues = [
        SubtitleCue(
            index=index + 1,
            start_ms=cue.start_ms,
            end_ms=cue.end_ms,
            text=(
                f"{speaker_map.get(cue.speaker_id, cue.speaker_id)}: {cue.text}"
                if include_speakers
                else cue.text
            ),
        )
        for index, cue in enumerate(cues)
    ]
    return render_srt(subtitle_cues)


def render_plain_text(cues: Sequence[TranscriptCue], speakers: Mapping[str, str] | None = None) -> str:
    speaker_map = speakers or {}
    lines: list[str] = []
    for cue in cues:
        speaker_label = speaker_map.get(cue.speaker_id, cue.speaker_id)
        lines.append(f"[{format_timestamp(cue.start_ms)} - {speaker_label}] {cue.text.strip()}")
    return "\n".join(lines) + ("\n" if lines else "")


def render_longform_script(
    cues: Sequence[TranscriptCue],
    speakers: Mapping[str, str] | None = None,
) -> str:
    speaker_map = speakers or {}
    lines: list[str] = []
    cursor_ms = 0
    for cue in cues:
        gap_ms = max(0, cue.start_ms - cursor_ms)
        if gap_ms:
            lines.append(f"[pause {gap_ms}ms]")
        label = speaker_map.get(cue.speaker_id, cue.speaker_id)
        lines.append(f"{label}: {cue.text.strip()}")
        cursor_ms = max(cursor_ms, cue.end_ms)
    return "\n".join(lines) + ("\n" if lines else "")


def parse_vtt(text: str) -> list[TranscriptCue]:
    normalized = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized.startswith("WEBVTT"):
        raise ValueError("File VTT phải bắt đầu bằng WEBVTT.")
    blocks = re.split(r"\n[ \t]*\n", normalized)
    cues: list[TranscriptCue] = []
    timestamp_pattern = re.compile(
        r"^(?:(\d{2,}):)?([0-5]\d):([0-5]\d)\.(\d{3})\s*-->\s*"
        r"(?:(\d{2,}):)?([0-5]\d):([0-5]\d)\.(\d{3})"
    )
    for block in blocks[1:]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        timing_line = lines[0] if "-->" in lines[0] else (lines[1] if len(lines) > 1 and "-->" in lines[1] else "")
        if not timing_line:
            continue
        match = timestamp_pattern.match(timing_line)
        if not match:
            continue
        v = [int(x or 0) for x in match.groups()]
        start_ms = v[0] * 3600000 + v[1] * 60000 + v[2] * 1000 + v[3]
        end_ms = v[4] * 3600000 + v[5] * 60000 + v[6] * 1000 + v[7]
        content_lines = lines[lines.index(timing_line) + 1 :]
        raw_text = "\n".join(content_lines)
        speaker_id = "speaker-1"
        voice_match = re.match(r"^<v\s+([^>]+)>(.*)$", raw_text, re.DOTALL)
        if voice_match:
            speaker_id = voice_match.group(1).strip()
            raw_text = voice_match.group(2).strip()
        raw_text = re.sub(r"<[^>]+>", "", raw_text).strip()
        if raw_text:
            cues.append(
                TranscriptCue(
                    cue_id=uuid4().hex,
                    position=len(cues),
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=raw_text,
                    speaker_id=speaker_id,
                )
            )
    return cues


class TranscriptService:
    def __init__(self, repository: TranscriptRepository) -> None:
        self.repository = repository

    def import_media(
        self,
        *,
        project_id: str,
        media_path: Path,
        name: str = "",
        language: str = "auto",
        model_size: str = "base",
        device: str = AUTO_DEVICE,
        diarization: bool = False,
        progress: ProgressCallback | None = None,
        stop_event: threading.Event | None = None,
    ) -> TranscriptProject:
        report = progress or (lambda _: None)
        path = Path(media_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Không tìm thấy file media: {path}")

        guard_output_space(
            Path(tempfile.gettempdir()),
            source_paths=(path,),
            minimum_mib=512,
            multiplier=2.5,
        )

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError(ffmpeg_missing_message("phiên âm audio/video"))

        project_name = name.strip() or path.stem
        is_video = path.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
        source_kind = "video" if is_video else "audio"

        warnings: list[str] = []
        with tempfile.TemporaryDirectory(prefix="galaxy_asr_") as workspace:
            audio_path = Path(workspace) / "speech.wav"
            report("Đang trích xuất audio...")
            _run_ffmpeg(
                build_extract_wav_command(ffmpeg, path, audio_path),
                _run_command,
                stop_event=stop_event,
            )

            report(f"Đang phiên âm bằng faster-whisper ({model_size})...")
            whisper_lang = None if language == "auto" else language
            cues, detected_lang, resolved_device = self._transcribe_detailed(
                audio_path,
                whisper_lang,
                model_size,
                report,
                device=device,
                stop_event=stop_event,
            )

            speakers = [TranscriptSpeaker(speaker_id="speaker-1", label="Người nói 1")]
            diarization_state = "disabled"
            turns: tuple[SpeakerTurn, ...] = ()
            if diarization:
                report("Đang phân tách người nói (diarization)...")
                turns, diarization_state, warning = self._diarize(
                    audio_path,
                    device=device,
                    stop_event=stop_event,
                )
                if warning:
                    warnings.append(warning)
                    report(warning)
                if turns:
                    cues = self._assign_speakers(cues, turns)
                    speaker_ids = sorted({cue.speaker_id for cue in cues})
                    colors = ("#d08ca1", "#7db196", "#d6ae66", "#7aa7c7", "#b696d4")
                    speakers = [
                        TranscriptSpeaker(
                            speaker_id=speaker_id,
                            label=f"Người nói {index + 1}",
                            color=colors[index % len(colors)],
                        )
                        for index, speaker_id in enumerate(speaker_ids)
                    ]

            project = TranscriptProject.create(
                project_id=project_id,
                name=project_name,
                source_path=str(path),
                source_kind=source_kind,
                requested_language=language,
                detected_language=detected_lang or language,
                model_id=model_size,
                requested_device=device,
                diarization_requested=diarization,
                cues=tuple(cues),
                status="ready",
            )
            if turns:
                speakers = self._extract_speaker_references(
                    ffmpeg,
                    audio_path,
                    project.transcript_id,
                    speakers,
                    turns,
                    report,
                    stop_event,
                )
            project = replace(
                project,
                speakers=tuple(speakers),
                resolved_device=resolved_device,
                diarization_state=diarization_state,
                warnings=tuple(warnings),
                provenance={
                    "asr_engine": "faster-whisper",
                    "model_id": model_size,
                    "requested_device": device,
                    "resolved_device": resolved_device,
                    "word_timestamps": True,
                    "diarization_engine": "pyannote" if diarization else "",
                },
            )

        saved = self.repository.create(project)
        report(f"Hoàn tất: {len(cues)} đoạn thoại.")
        return saved

    def import_text(
        self,
        *,
        project_id: str,
        name: str,
        content: str,
        format_type: str = "srt",
        language: str = "vi",
        source_path: str = "",
    ) -> TranscriptProject:
        fmt = format_type.lower().strip()
        if fmt == "srt":
            subtitle_cues = parse_srt(content)
            cues = tuple(
                TranscriptCue(
                    cue_id=uuid4().hex,
                    position=index,
                    start_ms=cue.start_ms,
                    end_ms=cue.end_ms,
                    text=cue.text,
                    speaker_id="speaker-1",
                )
                for index, cue in enumerate(subtitle_cues)
            )
        elif fmt == "vtt":
            cues = tuple(parse_vtt(content))
        else:
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            cues = tuple(
                TranscriptCue(
                    cue_id=uuid4().hex,
                    position=index,
                    start_ms=index * 3000,
                    end_ms=(index + 1) * 3000,
                    text=line,
                    speaker_id="speaker-1",
                )
                for index, line in enumerate(lines)
            )

        if not cues:
            raise ValueError("Không tìm thấy nội dung hợp lệ trong file import.")

        project = TranscriptProject.create(
            project_id=project_id,
            name=name.strip() or "Imported Transcript",
            source_path=source_path,
            source_kind="document",
            requested_language=language,
            model_id="import",
            requested_device="none",
            diarization_requested=False,
            cues=cues,
            detected_language=language,
            status="ready",
        )
        imported_speaker_ids = list(dict.fromkeys(cue.speaker_id for cue in cues))
        if imported_speaker_ids != ["speaker-1"]:
            colors = ("#d08ca1", "#7db196", "#d6ae66", "#7aa7c7", "#b696d4")
            project = replace(
                project,
                speakers=tuple(
                    TranscriptSpeaker(
                        speaker_id=speaker_id,
                        label=speaker_id,
                        color=colors[index % len(colors)],
                    )
                    for index, speaker_id in enumerate(imported_speaker_ids)
                ),
            )
        return self.repository.create(project)

    def edit_cue(
        self,
        transcript_id: str,
        cue_id: str,
        *,
        text: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        speaker_id: str | None = None,
        expected_revision: int | None = None,
    ) -> TranscriptProject:
        def _apply(current: TranscriptProject) -> TranscriptProject:
            updated_cues: list[TranscriptCue] = []
            found = False
            for cue in current.cues:
                if cue.cue_id == cue_id:
                    found = True
                    new_start = cue.start_ms if start_ms is None else start_ms
                    new_end = cue.end_ms if end_ms is None else end_ms
                    if new_end <= new_start:
                        raise ValueError("Thời điểm kết thúc phải lớn hơn thời điểm bắt đầu.")
                    updated_cues.append(
                        replace(
                            cue,
                            text=cue.text if text is None else text.strip(),
                            start_ms=new_start,
                            end_ms=new_end,
                            speaker_id=cue.speaker_id if speaker_id is None else speaker_id,
                        )
                    )
                else:
                    updated_cues.append(cue)
            if not found:
                raise KeyError(f"Không tìm thấy cue: {cue_id}")
            return current.evolved(cues=normalize_cues(tuple(updated_cues)))

        return self.repository.mutate(transcript_id, _apply, expected_revision=expected_revision)

    def replace_document(
        self,
        transcript_id: str,
        *,
        cues: Sequence[Mapping[str, Any]],
        speakers: Sequence[Mapping[str, Any]],
        expected_revision: int,
    ) -> TranscriptProject:
        parsed_cues = normalize_cues(tuple(TranscriptCue.from_dict(item) for item in cues))
        parsed_speakers = tuple(TranscriptSpeaker.from_dict(item) for item in speakers)
        if not parsed_cues:
            raise ValueError("Transcript cần ít nhất một cue.")
        if not parsed_speakers:
            raise ValueError("Transcript cần ít nhất một người nói.")

        def _apply(current: TranscriptProject) -> TranscriptProject:
            duration = max((cue.end_ms for cue in parsed_cues), default=0)
            return current.evolved(
                cues=parsed_cues,
                speakers=parsed_speakers,
                duration_ms=duration,
            )

        return self.repository.mutate(
            transcript_id,
            _apply,
            expected_revision=expected_revision,
        )

    def split_cue(
        self,
        transcript_id: str,
        cue_id: str,
        split_ms: int,
        first_text: str,
        second_text: str,
        *,
        expected_revision: int | None = None,
    ) -> TranscriptProject:
        def _apply(current: TranscriptProject) -> TranscriptProject:
            updated: list[TranscriptCue] = []
            found = False
            for cue in current.cues:
                if cue.cue_id == cue_id:
                    found = True
                    if not (cue.start_ms < split_ms < cue.end_ms):
                        raise ValueError("Điểm cắt phải nằm trong khoảng thời gian của cue.")
                    first_words = tuple(
                        word
                        for word in cue.words
                        if (word.start_ms + word.end_ms) / 2 < split_ms
                    )
                    second_words = tuple(
                        word
                        for word in cue.words
                        if (word.start_ms + word.end_ms) / 2 >= split_ms
                    )
                    updated.append(
                        replace(
                            cue,
                            end_ms=split_ms,
                            text=first_text.strip(),
                            words=first_words,
                        )
                    )
                    updated.append(
                        TranscriptCue(
                            cue_id=uuid4().hex,
                            position=cue.position + 1,
                            start_ms=split_ms,
                            end_ms=cue.end_ms,
                            text=second_text.strip(),
                            speaker_id=cue.speaker_id,
                            words=second_words,
                        )
                    )
                else:
                    updated.append(cue)
            if not found:
                raise KeyError(cue_id)
            return current.evolved(cues=normalize_cues(tuple(updated)))

        return self.repository.mutate(transcript_id, _apply, expected_revision=expected_revision)

    def merge_cues(
        self,
        transcript_id: str,
        first_cue_id: str,
        second_cue_id: str,
        *,
        separator: str = " ",
        expected_revision: int | None = None,
    ) -> TranscriptProject:
        def _apply(current: TranscriptProject) -> TranscriptProject:
            first = next((c for c in current.cues if c.cue_id == first_cue_id), None)
            second = next((c for c in current.cues if c.cue_id == second_cue_id), None)
            if not first or not second:
                raise KeyError("Không tìm thấy cue cần ghép.")
            merged = replace(
                first,
                end_ms=max(first.end_ms, second.end_ms),
                text=f"{first.text.strip()}{separator}{second.text.strip()}",
                words=(*first.words, *second.words),
            )
            kept = [merged if c.cue_id == first_cue_id else c for c in current.cues if c.cue_id != second_cue_id]
            return current.evolved(cues=normalize_cues(tuple(kept)))

        return self.repository.mutate(transcript_id, _apply, expected_revision=expected_revision)

    def delete_cue(
        self,
        transcript_id: str,
        cue_id: str,
        *,
        expected_revision: int | None = None,
    ) -> TranscriptProject:
        def _apply(current: TranscriptProject) -> TranscriptProject:
            remaining = [c for c in current.cues if c.cue_id != cue_id]
            if len(remaining) == len(current.cues):
                raise KeyError(cue_id)
            if not remaining:
                raise ValueError("Không thể xóa cue cuối cùng của transcript.")
            return current.evolved(cues=normalize_cues(tuple(remaining)))

        return self.repository.mutate(transcript_id, _apply, expected_revision=expected_revision)

    def add_speaker(
        self,
        transcript_id: str,
        label: str,
        color: str = "#d08ca1",
        *,
        expected_revision: int | None = None,
    ) -> TranscriptProject:
        def _apply(current: TranscriptProject) -> TranscriptProject:
            speaker_id = f"speaker-{len(current.speakers) + 1}"
            speaker = TranscriptSpeaker(speaker_id=speaker_id, label=label.strip() or f"Người nói {len(current.speakers) + 1}", color=color)
            return current.evolved(speakers=(*current.speakers, speaker))

        return self.repository.mutate(transcript_id, _apply, expected_revision=expected_revision)

    def update_speaker(
        self,
        transcript_id: str,
        speaker_id: str,
        label: str,
        color: str = "",
        *,
        expected_revision: int | None = None,
    ) -> TranscriptProject:
        def _apply(current: TranscriptProject) -> TranscriptProject:
            if not any(s.speaker_id == speaker_id for s in current.speakers):
                raise KeyError(speaker_id)
            updated = [
                replace(s, label=label.strip() or s.label, color=color or s.color)
                if s.speaker_id == speaker_id
                else s
                for s in current.speakers
            ]
            return current.evolved(speakers=tuple(updated))

        return self.repository.mutate(transcript_id, _apply, expected_revision=expected_revision)

    def record_handoff(self, transcript_id: str, target: str) -> tuple[TranscriptProject, dict[str, Any]]:
        normalized_target = target.strip().casefold()
        if normalized_target not in {"dubbing", "longform"}:
            raise ValueError("Đích handoff phải là dubbing hoặc longform.")

        def _apply(current: TranscriptProject) -> TranscriptProject:
            handoff = {
                "handoff_id": uuid4().hex,
                "target": normalized_target,
                "created_at": utc_now(),
                "source_revision": current.revision,
            }
            return current.evolved(handoffs=(*current.handoffs, handoff))

        updated = self.repository.mutate(transcript_id, _apply)
        handoff = updated.handoffs[-1]
        return updated, self._build_handoff_payload(updated, normalized_target, handoff)

    def get_handoff(self, transcript_id: str, target: str) -> dict[str, Any]:
        normalized_target = target.strip().casefold()
        if normalized_target not in {"dubbing", "longform"}:
            raise ValueError("Đích handoff phải là dubbing hoặc longform.")
        project = self.repository.get(transcript_id)
        if not project:
            raise KeyError(transcript_id)
        handoff = next(
            (
                item
                for item in reversed(project.handoffs)
                if str(item.get("target") or "") == normalized_target
            ),
            None,
        )
        if handoff is None:
            raise KeyError(f"handoff:{normalized_target}")
        return self._build_handoff_payload(project, normalized_target, handoff)

    def _build_handoff_payload(
        self,
        project: TranscriptProject,
        target: str,
        handoff: Mapping[str, Any],
    ) -> dict[str, Any]:
        speaker_labels = {speaker.speaker_id: speaker.label for speaker in project.speakers}
        payload: dict[str, Any] = {
            "schema_version": 1,
            "kind": "transcript_handoff",
            "handoff_id": str(handoff.get("handoff_id") or ""),
            "target": target,
            "transcript_id": project.transcript_id,
            "project_id": project.project_id,
            "source_revision": int(handoff.get("source_revision") or project.revision),
            "source_path": project.source_path,
            "language": project.detected_language or project.requested_language,
        }
        if target == "dubbing":
            payload["srt_text"] = render_transcript_srt(project.cues, speaker_labels)
            payload["segments"] = self._dubbing_segments(project, speaker_labels)
        else:
            payload["text"] = render_longform_script(project.cues, speaker_labels)
        return payload

    def export_text(
        self,
        transcript_id: str,
        format_type: str = "srt",
    ) -> str:
        project = self.repository.get(transcript_id)
        if not project:
            raise KeyError(transcript_id)
        fmt = format_type.lower().strip()
        speaker_labels = {s.speaker_id: s.label for s in project.speakers}
        if fmt == "vtt":
            return render_vtt(project.cues, speaker_labels)
        if fmt == "txt":
            return render_plain_text(project.cues, speaker_labels)
        return render_transcript_srt(project.cues, speaker_labels)

    def export_dubbing_handoff(self, transcript_id: str) -> list[dict[str, Any]]:
        project = self.repository.get(transcript_id)
        if not project:
            raise KeyError(transcript_id)
        speaker_labels = {speaker.speaker_id: speaker.label for speaker in project.speakers}
        return self._dubbing_segments(project, speaker_labels)

    @staticmethod
    def _dubbing_segments(
        project: TranscriptProject,
        speaker_labels: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        return [
            {
                "segment_id": cue.cue_id,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "source_text": cue.text,
                "text": cue.text,
                "speaker_id": speaker_labels.get(cue.speaker_id, cue.speaker_id),
                "source_speaker_id": cue.speaker_id,
                "profile_id": "",
                "speed": 1.0,
                "volume": 1.0,
            }
            for cue in project.cues
        ]

    def _transcribe_detailed(
        self,
        audio_path: Path,
        source_language: str | None,
        model_size: str,
        progress: ProgressCallback,
        device: str = AUTO_DEVICE,
        stop_event: threading.Event | None = None,
    ) -> tuple[list[TranscriptCue], str, str]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "faster-whisper chưa được cài. Hãy chạy: pip install -r requirements-transcription.txt"
            ) from error

        selected_device = normalize_processing_device(device)
        dev, compute_type = resolve_whisper_runtime(selected_device)
        try:
            cues, detected = self._transcribe_runtime(
                WhisperModel,
                audio_path,
                source_language,
                model_size,
                dev,
                compute_type,
                progress,
                stop_event,
            )
            return cues, detected, dev
        except Exception as error:
            if dev != "cuda" or selected_device != AUTO_DEVICE or isinstance(error, TaskCancelledError):
                raise
            progress(f"CUDA ASR lỗi: {error}. Đang chuyển sang CPU...")
            cues, detected = self._transcribe_runtime(
                WhisperModel,
                audio_path,
                source_language,
                model_size,
                "cpu",
                "int8",
                progress,
                stop_event,
            )
            return cues, detected, "cpu"

    @staticmethod
    def _transcribe_runtime(
        whisper_model_class: Any,
        audio_path: Path,
        source_language: str | None,
        model_size: str,
        device: str,
        compute_type: str,
        progress: ProgressCallback,
        stop_event: threading.Event | None,
    ) -> tuple[list[TranscriptCue], str]:
        progress(f"Đang nạp mô hình Whisper: {model_size} ({device.upper()})")
        model = whisper_model_class(model_size, device=device, compute_type=compute_type)

        segments, info = model.transcribe(
            str(audio_path),
            language=source_language,
            vad_filter=True,
            beam_size=5,
            word_timestamps=True,
        )

        detected_lang = getattr(info, "language", "") or (source_language or "vi")
        cues: list[TranscriptCue] = []
        for index, segment in enumerate(segments):
            if stop_event is not None and stop_event.is_set():
                raise TaskCancelledError()
            text = str(segment.text).strip()
            if not text:
                continue
            words = []
            for w in getattr(segment, "words", ()) or ():
                w_text = str(getattr(w, "word", "")).strip()
                word_start = getattr(w, "start", None)
                word_end = getattr(w, "end", None)
                if w_text and word_start is not None and word_end is not None:
                    words.append(
                        TranscriptWord(
                            word_id=uuid4().hex,
                            text=w_text,
                            start_ms=round(float(word_start) * 1000),
                            end_ms=round(float(word_end) * 1000),
                            confidence=float(getattr(w, "probability", 1.0)),
                        )
                    )
            cues.append(
                TranscriptCue(
                    cue_id=uuid4().hex,
                    position=len(cues),
                    start_ms=round(float(segment.start) * 1000),
                    end_ms=round(float(segment.end) * 1000),
                    text=text,
                    speaker_id="speaker-1",
                    confidence=(
                        sum(word.confidence or 0 for word in words) / len(words)
                        if words
                        else None
                    ),
                    words=tuple(words),
                )
            )
            if (index + 1) % 10 == 0:
                progress(f"Đã xử lý {index + 1} đoạn...")

        if not cues:
            raise RuntimeError("Không phát hiện được lời nói trong media.")
        return cues, detected_lang

    @staticmethod
    def _diarize(
        audio_path: Path,
        *,
        device: str,
        stop_event: threading.Event | None,
    ) -> tuple[tuple[SpeakerTurn, ...], str, str]:
        try:
            installed = importlib.util.find_spec("pyannote.audio") is not None
        except ModuleNotFoundError:
            installed = False
        if not installed:
            return (), "unavailable", "Chưa cài pyannote.audio; vẫn có thể gán người nói thủ công."
        token = next(
            (
                os.environ.get(name, "").strip()
                for name in ("GALAXY_HF_TOKEN", "HF_TOKEN", "HUGGINGFACE_HUB_TOKEN")
                if os.environ.get(name, "").strip()
            ),
            "",
        )
        if not token:
            return (), "missing_token", "Thiếu GALAXY_HF_TOKEN cho diarization; vẫn có thể gán người nói thủ công."
        if stop_event is not None and stop_event.is_set():
            raise TaskCancelledError()
        try:
            import torch
            from pyannote.audio import Pipeline

            resolved_device = resolve_diarization_device(device)

            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=token,
            )
            if pipeline is None:
                raise RuntimeError("Không tải được model pyannote/speaker-diarization-3.1.")
            if resolved_device == "cuda":
                pipeline.to(torch.device("cuda"))
            result = pipeline(str(audio_path))
            annotation = getattr(result, "speaker_diarization", result)
            turns = tuple(
                SpeakerTurn(
                    speaker_id=str(label),
                    start_ms=round(float(turn.start) * 1000),
                    end_ms=round(float(turn.end) * 1000),
                )
                for turn, _track, label in annotation.itertracks(yield_label=True)
                if float(turn.end) > float(turn.start)
            )
            return turns, "complete" if turns else "no_speakers", ""
        except TaskCancelledError:
            raise
        except Exception as error:
            return (), "failed", f"Diarization không chạy được: {error}. Có thể gán người nói thủ công."

    @staticmethod
    def _assign_speakers(
        cues: Sequence[TranscriptCue],
        turns: Sequence[SpeakerTurn],
    ) -> list[TranscriptCue]:
        assigned: list[TranscriptCue] = []
        for cue in cues:
            best = max(
                turns,
                key=lambda turn: max(
                    0,
                    min(cue.end_ms, turn.end_ms) - max(cue.start_ms, turn.start_ms),
                ),
            )
            overlap = max(0, min(cue.end_ms, best.end_ms) - max(cue.start_ms, best.start_ms))
            assigned.append(replace(cue, speaker_id=best.speaker_id if overlap else cue.speaker_id))
        return assigned

    def _extract_speaker_references(
        self,
        ffmpeg: str,
        audio_path: Path,
        transcript_id: str,
        speakers: Sequence[TranscriptSpeaker],
        turns: Sequence[SpeakerTurn],
        progress: ProgressCallback,
        stop_event: threading.Event | None,
    ) -> list[TranscriptSpeaker]:
        reference_dir = self.repository.project_dir(transcript_id) / "speaker-references"
        reference_dir.mkdir(parents=True, exist_ok=True)
        updated: list[TranscriptSpeaker] = []
        for speaker in speakers:
            candidates = [turn for turn in turns if turn.speaker_id == speaker.speaker_id]
            if not candidates:
                updated.append(speaker)
                continue
            turn = max(candidates, key=lambda item: item.end_ms - item.start_ms)
            duration_ms = min(15_000, turn.end_ms - turn.start_ms)
            output = reference_dir / f"{speaker.speaker_id}.wav"
            command = [
                ffmpeg,
                "-y",
                "-ss",
                f"{turn.start_ms / 1000:.3f}",
                "-t",
                f"{duration_ms / 1000:.3f}",
                "-i",
                str(audio_path),
                "-ac",
                "1",
                "-ar",
                "24000",
                str(output),
            ]
            try:
                _run_ffmpeg(command, _run_command, stop_event=stop_event)
                updated.append(
                    replace(
                        speaker,
                        reference_path=str(output),
                        reference_start_ms=turn.start_ms,
                        reference_end_ms=turn.start_ms + duration_ms,
                    )
                )
            except Exception as error:
                progress(f"Không trích được audio mẫu cho {speaker.label}: {error}")
                updated.append(speaker)
        return updated
