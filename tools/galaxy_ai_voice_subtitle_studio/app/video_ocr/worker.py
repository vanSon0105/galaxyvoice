from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from app.video_ocr.models import OcrBox, OcrObservation
from app.video_ocr.pipeline import FrameProbe, ProbeRun, group_probes, representative_probes, rescue_probe
from app.video_ocr.tracking import drop_static_cues, merge_observations, vote_observations
from app.voice.srt import SubtitleCue, render_srt


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recognize burned-in video subtitles.")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=("fast", "accurate"), default="fast")
    parser.add_argument("--language", default="vi")
    parser.add_argument("--region", nargs=4, type=int, required=True, metavar=("X", "Y", "W", "H"))
    return parser.parse_args()


def _load_dependencies():
    try:
        import cv2
        import numpy as np
        from rapidocr import ModelType, RapidOCR
    except ImportError as error:
        raise RuntimeError("Runtime OCR thieu RapidOCR, OpenCV hoac NumPy. Hay cai lai runtime OCR.") from error
    return cv2, np, ModelType, RapidOCR


def _engine(mode: str, language: str, ModelType, RapidOCR):
    model_type = ModelType.SMALL if mode == "accurate" else ModelType.TINY
    recognition_language = {
        "vi": "latin",
        "en": "en",
        "ch": "ch",
        "japan": "japan",
    }.get(language.strip().casefold(), "latin")
    return RapidOCR(
        params={
            "Det.model_type": model_type,
            "Rec.ocr_version": "PP-OCRv5",
            "Rec.lang_type": recognition_language,
            "Rec.model_type": ModelType.MOBILE,
            "Global.log_level": "error",
        }
    )


def _pixel_region(frame, region: tuple[int, int, int, int]):
    height, width = frame.shape[:2]
    x, y, region_width, region_height = region
    left = max(0, min(width - 1, round(width * x / 100)))
    top = max(0, min(height - 1, round(height * y / 100)))
    right = max(left + 1, min(width, round(width * (x + region_width) / 100)))
    bottom = max(top + 1, min(height, round(height * (y + region_height) / 100)))
    return left, top, right, bottom


def _fingerprint(image, cv2, np) -> tuple[bytes, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    kernel_width = max(3, round(image.shape[1] / 160))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width | 1, 3))
    light_text = cv2.morphologyEx(blurred, cv2.MORPH_TOPHAT, kernel)
    dark_text = cv2.morphologyEx(blurred, cv2.MORPH_BLACKHAT, kernel)
    probable_text = cv2.max(light_text, dark_text)
    reduced = cv2.resize(probable_text, (64, 24), interpolation=cv2.INTER_AREA)
    _threshold, ink = cv2.threshold(reduced, 18, 255, cv2.THRESH_BINARY)
    return np.packbits(ink > 0).tobytes(), float(np.count_nonzero(ink)) / ink.size


def _prepare_patch(patch, mode: str, cv2):
    maximum_width = 1440 if mode == "accurate" else 960
    if patch.shape[1] <= maximum_width:
        return patch, 1.0
    scale = maximum_width / patch.shape[1]
    resized = cv2.resize(
        patch,
        (maximum_width, max(1, round(patch.shape[0] * scale))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def _recognize(engine, patch, *, offset: tuple[int, int], scale: float) -> OcrObservation:
    result = engine(patch)
    texts = tuple(result.txts or ())
    scores = tuple(float(value) for value in (result.scores or ()))
    boxes = result.boxes
    if not texts or boxes is None:
        return OcrObservation(0, "", 0.0)

    lines = []
    for index, text in enumerate(texts):
        value = str(text).strip()
        if not value:
            continue
        points = boxes[index]
        left = min(float(point[0]) for point in points) / scale + offset[0]
        top = min(float(point[1]) for point in points) / scale + offset[1]
        right = max(float(point[0]) for point in points) / scale + offset[0]
        bottom = max(float(point[1]) for point in points) / scale + offset[1]
        score = scores[index] if index < len(scores) else 0.0
        lines.append((top, left, value, score, OcrBox(round(left), round(top), max(1, round(right - left)), max(1, round(bottom - top)))))
    lines.sort(key=lambda item: (round(item[0] / 12), item[1]))
    return OcrObservation(
        0,
        "\n".join(item[2] for item in lines),
        sum(item[3] for item in lines) / len(lines) if lines else 0.0,
        tuple(item[4] for item in lines),
    )


def _scan_probes(
    capture,
    *,
    cv2,
    np,
    region: tuple[int, int, int, int],
    fps: float,
    frame_count: int,
    sample_every: int,
) -> tuple[FrameProbe, ...]:
    probes: list[FrameProbe] = []
    frame_index = 0
    while True:
        received = capture.grab()
        if not received:
            break
        if frame_index % sample_every != 0:
            frame_index += 1
            continue
        received, frame = capture.retrieve()
        if received:
            left, top, right, bottom = _pixel_region(frame, region)
            signature, activity = _fingerprint(frame[top:bottom, left:right], cv2, np)
            probes.append(FrameProbe(frame_index, round(frame_index * 1000 / fps), signature, activity))
            if len(probes) % 40 == 0:
                percent = min(48, round(frame_index * 48 / max(1, frame_count)))
                print(f"OCR {percent}%: da quet {len(probes)} frame mau.", flush=True)
        frame_index += 1
    return tuple(probes)


def _recognize_probes(
    video_path: Path,
    probes: tuple[FrameProbe, ...],
    *,
    cv2,
    engine,
    mode: str,
    region: tuple[int, int, int, int],
    progress_start: int,
    progress_span: int,
) -> dict[int, OcrObservation]:
    wanted = {probe.frame_index: probe for probe in probes}
    if not wanted:
        return {}
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Khong mo duoc video o luot OCR: {video_path}")
    observations: dict[int, OcrObservation] = {}
    ordered = sorted(wanted)
    next_position = 0
    try:
        for completed, target in enumerate(ordered, start=1):
            if target < next_position:
                capture.set(cv2.CAP_PROP_POS_FRAMES, target)
                next_position = target
            while next_position <= target:
                received = capture.grab()
                if not received:
                    break
                next_position += 1
            else:
                received, frame = capture.retrieve()
                if received:
                    left, top, right, bottom = _pixel_region(frame, region)
                    prepared, scale = _prepare_patch(frame[top:bottom, left:right], mode, cv2)
                    recognized = _recognize(engine, prepared, offset=(left, top), scale=scale)
                    probe = wanted[target]
                    observations[target] = OcrObservation(
                        probe.timestamp_ms,
                        recognized.text,
                        recognized.confidence,
                        recognized.boxes,
                    )
            if completed % 10 == 0 or completed == len(ordered):
                percent = progress_start + round(completed * progress_span / len(ordered))
                print(f"OCR {percent}%: da nhan dang {completed}/{len(ordered)} frame dai dien.", flush=True)
    finally:
        capture.release()
    return observations


def _run_winner(
    run: ProbeRun,
    recognized: dict[int, OcrObservation],
    *,
    similarity_threshold: float,
) -> OcrObservation:
    observations = tuple(recognized[probe.frame_index] for probe in run.probes if probe.frame_index in recognized)
    winner = vote_observations(observations, similarity_threshold=similarity_threshold)
    return OcrObservation(run.probes[0].timestamp_ms, winner.text, winner.confidence, winner.boxes)


def run(video_path: Path, output_dir: Path, mode: str, language: str, region: tuple[int, int, int, int]) -> dict[str, object]:
    cv2, np, ModelType, RapidOCR = _load_dependencies()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Khong mo duoc video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 30.0
    frame_count = max(0, round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    duration_ms = max(1, round(frame_count * 1000 / fps))
    sample_fps = 4.0 if mode == "accurate" else 2.0
    sample_interval_ms = round(1000 / sample_fps)
    sample_every = max(1, math.ceil(fps / sample_fps))
    started = time.perf_counter()
    try:
        probes = _scan_probes(
            capture,
            cv2=cv2,
            np=np,
            region=region,
            fps=fps,
            frame_count=frame_count,
            sample_every=sample_every,
        )
    finally:
        capture.release()
    if probes:
        duration_ms = max(duration_ms, probes[-1].timestamp_ms + sample_interval_ms)

    runs = group_probes(
        probes,
        change_threshold=48 if mode == "accurate" else 64,
        maximum_run_ms=1_800 if mode == "accurate" else 2_800,
    )
    primary = tuple({
        probe.frame_index: probe
        for run in runs
        for probe in representative_probes(run, accurate=mode == "accurate")
    }.values())
    primary_frame_indices = {probe.frame_index for probe in primary}
    engine = _engine(mode, language, ModelType, RapidOCR)
    recognized = _recognize_probes(
        video_path,
        primary,
        cv2=cv2,
        engine=engine,
        mode=mode,
        region=region,
        progress_start=50,
        progress_span=35,
    )
    similarity_threshold = 0.88 if mode == "accurate" else 0.82
    confidence_floor = 0.62 if mode == "accurate" else 0.52
    rescue = tuple(
        candidate
        for run in runs
        if (winner := _run_winner(run, recognized, similarity_threshold=similarity_threshold)).confidence < confidence_floor
        if (candidate := rescue_probe(run, excluded_frame_indices=primary_frame_indices)) is not None
    )
    rescued = _recognize_probes(
        video_path,
        rescue,
        cv2=cv2,
        engine=engine,
        mode=mode,
        region=region,
        progress_start=85,
        progress_span=12,
    )
    recognized.update(rescued)

    observations: list[OcrObservation] = []
    for run in runs:
        winner = _run_winner(run, recognized, similarity_threshold=similarity_threshold)
        observations.extend(
            OcrObservation(probe.timestamp_ms, winner.text, winner.confidence, winner.boxes)
            for probe in run.probes
        )

    cues = merge_observations(
        observations,
        sample_interval_ms=sample_interval_ms,
        duration_ms=duration_ms,
        similarity_threshold=similarity_threshold,
    )
    # Static-looking text can be a watermark, but it can also be a valid long
    # subtitle on a short clip. Keep it editable and expose it only as a review
    # candidate instead of silently deleting it from the SRT.
    _non_static_cues, static_cues = drop_static_cues(cues, duration_ms=duration_ms)
    sampled_frames = len(probes)
    ocr_frames = len(recognized)
    reused_frames = max(0, sampled_frames - ocr_frames)
    output_dir.mkdir(parents=True, exist_ok=True)
    srt_path = output_dir / "captions.srt"
    srt_path.write_text(
        render_srt([SubtitleCue(cue.index, cue.start_ms, cue.end_ms, cue.text) for cue in cues]),
        encoding="utf-8",
    )
    manifest_path = output_dir / "ocr_manifest.json"
    payload = {
        "version": 2,
        "pipeline": "two-pass-selective",
        "source_video_path": str(video_path),
        "mode": mode,
        "language": language,
        "region": {"x": region[0], "y": region[1], "width": region[2], "height": region[3]},
        "sample_fps": sample_fps,
        "duration_ms": duration_ms,
        "sampled_frames": sampled_frames,
        "ocr_frames": ocr_frames,
        "reused_frames": reused_frames,
        "probe_runs": len(runs),
        "rescue_frames": len(rescued),
        "discarded_static_cues": 0,
        "static_candidates": [
            {
                "index": cue.index,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "text": cue.text,
                "confidence": round(cue.confidence, 4),
                "boxes": [box.__dict__ for box in cue.boxes],
            }
            for cue in static_cues
        ],
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "cues": [
            {
                "index": cue.index,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "text": cue.text,
                "confidence": round(cue.confidence, 4),
                "boxes": [box.__dict__ for box in cue.boxes],
            }
            for cue in cues
        ],
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    args = _arguments()
    try:
        payload = run(args.video, args.output, args.mode, args.language, tuple(args.region))
    except Exception as error:
        print(f"OCR that bai: {error}", file=sys.stderr, flush=True)
        return 1
    print("GALAXY_OCR_RESULT:" + json.dumps(payload, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
