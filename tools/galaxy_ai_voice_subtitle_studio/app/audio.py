from __future__ import annotations

import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg import find_ffmpeg


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
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.strip() or "ffmpeg failed while exporting MP3."
        return False, message

    return True, "MP3 exported."


def _assert_compatible(reference: wave._wave_params, candidate: wave._wave_params, path: Path) -> None:
    ref = (reference.nchannels, reference.sampwidth, reference.framerate, reference.comptype)
    got = (candidate.nchannels, candidate.sampwidth, candidate.framerate, candidate.comptype)
    if ref != got:
        raise ValueError(f"WAV segment has a different audio format: {path}")
