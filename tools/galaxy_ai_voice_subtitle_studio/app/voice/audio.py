from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

from ..common.ffmpeg import find_ffmpeg
from .media import _run_command


@dataclass(frozen=True)
class AudioTiming:
    start_ms: int
    end_ms: int
    duration_ms: int


def wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        framerate = handle.getframerate()
        if framerate <= 0:
            return 0
        return round(frames * 1000 / framerate)


def concatenate_wavs(segment_paths: list[Path], output_path: Path, gap_ms: int = 250) -> list[AudioTiming]:
    if not segment_paths:
        raise ValueError("No WAV segments were provided.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    gap_ms = max(0, int(gap_ms))

    with wave.open(str(segment_paths[0]), "rb") as first:
        params = first.getparams()

    timings: list[AudioTiming] = []
    current_ms = 0

    with wave.open(str(output_path), "wb") as output:
        output.setparams(params)

        for index, path in enumerate(segment_paths):
            with wave.open(str(path), "rb") as segment:
                _assert_compatible(params, segment.getparams(), path)
                frames = segment.readframes(segment.getnframes())
                frame_count = segment.getnframes()

            duration_ms = round(frame_count * 1000 / params.framerate)
            start_ms = current_ms
            end_ms = start_ms + duration_ms
            output.writeframes(frames)
            timings.append(AudioTiming(start_ms=start_ms, end_ms=end_ms, duration_ms=duration_ms))

            current_ms = end_ms
            if index < len(segment_paths) - 1 and gap_ms:
                silence_frames = round(params.framerate * gap_ms / 1000)
                output.writeframes(b"\x00" * silence_frames * params.nchannels * params.sampwidth)
                current_ms += round(silence_frames * 1000 / params.framerate)

    return timings


def split_wav_on_silence(
    source_path: Path,
    output_paths: list[Path],
    *,
    weights: list[int],
    minimum_silence_ms: int = 120,
) -> bool:
    if len(output_paths) != len(weights) or len(output_paths) < 2:
        raise ValueError("WAV split needs matching output paths and weights for at least two cues.")
    if any(weight <= 0 for weight in weights):
        raise ValueError("WAV split weights must be positive.")

    try:
        with wave.open(str(source_path), "rb") as source:
            params = source.getparams()
            frames = source.readframes(source.getnframes())
        boundaries = _proven_silence_boundaries(frames, params, weights, minimum_silence_ms)
        if boundaries is None:
            return False
        frame_size = params.nchannels * params.sampwidth
        offsets = [0, *boundaries, params.nframes]
        for index, output_path in enumerate(output_paths):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(output_path), "wb") as output:
                output.setparams(params)
                output.writeframes(frames[offsets[index] * frame_size : offsets[index + 1] * frame_size])
    except (OSError, EOFError, wave.Error):
        for output_path in output_paths:
            output_path.unlink(missing_ok=True)
        return False
    return True


def _proven_silence_boundaries(
    frames: bytes,
    params: wave._wave_params,
    weights: list[int],
    minimum_silence_ms: int,
) -> list[int] | None:
    if params.comptype != "NONE" or params.nframes <= 0 or params.framerate <= 0:
        return None
    window_frames = max(1, params.framerate // 100)
    peaks = _window_peaks(frames, params, window_frames)
    if not peaks or max(peaks) <= 0:
        return None
    silence_threshold = max(1, round(max(peaks) * 0.02))
    minimum_windows = max(1, math.ceil(minimum_silence_ms * params.framerate / 1000 / window_frames))
    candidates: list[int] = []
    run_start: int | None = None
    for index, peak in enumerate([*peaks, silence_threshold + 1]):
        if peak <= silence_threshold and run_start is None:
            run_start = index
        elif peak > silence_threshold and run_start is not None:
            if run_start > 0 and index < len(peaks) and index - run_start >= minimum_windows:
                candidates.append(round((run_start + index) * window_frames / 2))
            run_start = None

    if len(candidates) != len(weights) - 1:
        return None

    total_weight = sum(weights)
    minimum_piece_frames = max(1, round(params.framerate * 0.08))
    tolerance_frames = max(
        round(params.framerate * 0.45),
        round(params.nframes / len(weights) * 0.4),
    )
    boundaries: list[int] = []
    consumed_weight = 0
    for boundary_index, weight in enumerate(weights[:-1]):
        consumed_weight += weight
        expected = round(params.nframes * consumed_weight / total_weight)
        remaining_pieces = len(weights) - boundary_index - 1
        lower = (boundaries[-1] if boundaries else 0) + minimum_piece_frames
        upper = params.nframes - remaining_pieces * minimum_piece_frames
        valid = [
            candidate
            for candidate in candidates
            if lower <= candidate <= upper and abs(candidate - expected) <= tolerance_frames
        ]
        if not valid:
            return None
        chosen = min(valid, key=lambda candidate: abs(candidate - expected))
        boundaries.append(chosen)
        candidates.remove(chosen)
    return boundaries


def _window_peaks(
    frames: bytes,
    params: wave._wave_params,
    window_frames: int,
) -> list[int]:
    frame_size = params.nchannels * params.sampwidth
    peaks: list[int] = []
    for frame_start in range(0, params.nframes, window_frames):
        byte_start = frame_start * frame_size
        byte_end = min(params.nframes, frame_start + window_frames) * frame_size
        peak = 0
        for offset in range(byte_start, byte_end, params.sampwidth):
            sample = frames[offset : offset + params.sampwidth]
            value = sample[0] - 128 if params.sampwidth == 1 else int.from_bytes(sample, "little", signed=True)
            peak = max(peak, abs(value))
        peaks.append(peak)
    return peaks


def try_convert_to_mp3(wav_path: Path, mp3_path: Path) -> tuple[bool, str]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg was not found; MP3 export was skipped."

    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(wav_path),
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(mp3_path),
    ]
    completed = _run_command(command)
    if completed.returncode != 0:
        message = completed.stderr.strip() or "ffmpeg failed while exporting MP3."
        return False, message

    return True, "MP3 exported."


def _assert_compatible(reference: wave._wave_params, candidate: wave._wave_params, path: Path) -> None:
    ref = (reference.nchannels, reference.sampwidth, reference.framerate, reference.comptype)
    got = (candidate.nchannels, candidate.sampwidth, candidate.framerate, candidate.comptype)
    if ref != got:
        raise ValueError(f"WAV segment has a different audio format: {path}")
