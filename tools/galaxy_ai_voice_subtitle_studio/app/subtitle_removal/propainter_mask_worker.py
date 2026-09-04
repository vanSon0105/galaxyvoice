from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build frame-wise subtitle masks for ProPainter.")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--roi", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    parser.add_argument(
        "--mask",
        action="append",
        nargs=6,
        type=float,
        metavar=("X", "Y", "W", "H", "START", "END"),
    )
    parser.add_argument("--time-offset", type=float, default=0.0)
    args = parser.parse_args()
    if args.roi is None and not args.mask:
        parser.error("one --roi or at least one --mask is required")
    return args


def _load_cv_dependencies():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Dynamic subtitle masking needs OpenCV and NumPy in the ProPainter environment. "
            "Run install_propainter.ps1 again."
        ) from exc
    return cv2, np


def _clip_roi(frame_width: int, frame_height: int, roi: tuple[int, int, int, int]):
    x, y, width, height = roi
    left = max(0, min(frame_width, x))
    top = max(0, min(frame_height, y))
    right = max(left, min(frame_width, x + width))
    bottom = max(top, min(frame_height, y + height))
    if right <= left or bottom <= top:
        raise RuntimeError("The subtitle mask region is outside the processing video.")
    return left, top, right - left, bottom - top


def _component_gap(first, second) -> int:
    first_left, _, first_width, _, _ = first
    second_left, _, second_width, _, _ = second
    first_right = first_left + first_width
    second_right = second_left + second_width
    return max(0, max(first_left, second_left) - min(first_right, second_right))


def _components_overlap_vertically(first, second) -> bool:
    _, first_top, _, first_height, _ = first
    _, second_top, _, second_height, _ = second
    return min(first_top + first_height, second_top + second_height) > max(first_top, second_top)


def _detect_subtitle_mask(frame, roi, cv2, np):
    frame_height, frame_width = frame.shape[:2]
    x, y, width, height = _clip_roi(frame_width, frame_height, roi)
    patch = frame[y : y + height, x : x + width]
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    value = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 2]

    light_pixels = ((value >= 170) & (gray >= 115)).astype(np.uint8)
    dark_pixels = (gray <= 90).astype(np.uint8)
    dark_neighborhood = cv2.dilate(
        dark_pixels,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
    )
    seeds = (light_pixels & dark_neighborhood).astype(np.uint8)

    row_counts = seeds.sum(axis=1).astype(np.float32)
    smoothed_rows = np.convolve(row_counts, np.ones(11, dtype=np.float32), mode="same")
    patch_mask = np.zeros((height, width), dtype=np.uint8)
    if smoothed_rows.size == 0 or float(smoothed_rows.max()) < max(3.0, width * 0.002):
        full_mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
        return full_mask, 0.0

    center_row = int(smoothed_rows.argmax())
    row_radius = max(12, round(height * 0.39))
    gated_seeds = np.zeros_like(seeds)
    row_start = max(0, center_row - row_radius)
    row_end = min(height, center_row + row_radius + 1)
    gated_seeds[row_start:row_end] = seeds[row_start:row_end]
    # Cover the subtitle outline and drop shadow as well as its bright fill.
    candidate = cv2.dilate(
        gated_seeds * 255,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)),
    )

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, connectivity=8)
    minimum_area = max(16, round(width * height * 0.0004))
    minimum_height = max(5, round(height * 0.07))
    components = {
        index: tuple(int(value) for value in stats[index])
        for index in range(1, component_count)
        if int(stats[index, cv2.CC_STAT_AREA]) >= minimum_area
        and int(stats[index, cv2.CC_STAT_HEIGHT]) >= minimum_height
    }
    if not components:
        full_mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
        return full_mask, 0.0

    dominant_id = max(components, key=lambda index: components[index][cv2.CC_STAT_AREA])
    dominant = components[dominant_id]
    if dominant[cv2.CC_STAT_WIDTH] < max(24, round(width * 0.08)):
        full_mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
        return full_mask, 0.0

    maximum_gap = max(24, round(width * 0.04))
    substantial_width = max(20, round(width * 0.04))
    substantial_area = round(width * height * 0.008)
    for component_id, component in components.items():
        keep = component_id == dominant_id
        keep = keep or component[cv2.CC_STAT_WIDTH] >= substantial_width
        keep = keep or component[cv2.CC_STAT_AREA] >= substantial_area
        keep = keep or (
            _component_gap(component, dominant) <= maximum_gap
            and _components_overlap_vertically(component, dominant)
        )
        if keep:
            patch_mask[labels == component_id] = 255

    full_mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
    full_mask[y : y + height, x : x + width] = patch_mask
    coverage = float(np.count_nonzero(patch_mask)) / float(width * height)
    return full_mask, coverage


def generate_masks(
    video_path: Path,
    output_dir: Path,
    roi: tuple[int, int, int, int] | None = None,
    *,
    masks: tuple[tuple[tuple[int, int, int, int], float, float | None], ...] = (),
    time_offset: float = 0.0,
) -> tuple[int, float]:
    cv2, np = _load_cv_dependencies()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"Mask output folder is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open the ProPainter input video: {video_path}")
    expected_frame_count = max(0, round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if fps <= 0:
        fps = 30.0

    frame_count = 0
    coverage_total = 0.0
    try:
        while True:
            received, frame = capture.read()
            if not received:
                break
            timestamp = max(0.0, time_offset) + frame_count / fps
            active_masks = [
                item
                for item in masks
                if item[1] <= timestamp and (item[2] is None or timestamp <= item[2])
            ]
            if masks:
                mask = np.zeros(frame.shape[:2], dtype=np.uint8)
                coverage = 0.0
                for active_roi, _start, _end in active_masks:
                    detected, selected_coverage = _detect_subtitle_mask(
                        frame, active_roi, cv2, np
                    )
                    mask = cv2.bitwise_or(mask, detected)
                    coverage += selected_coverage
            elif roi is not None:
                mask, coverage = _detect_subtitle_mask(frame, roi, cv2, np)
            else:
                raise RuntimeError("No subtitle mask regions were configured.")
            mask_path = output_dir / f"{frame_count:08d}.png"
            if not cv2.imwrite(str(mask_path), mask, [cv2.IMWRITE_PNG_COMPRESSION, 1]):
                raise RuntimeError(f"Could not write subtitle mask: {mask_path}")
            frame_count += 1
            coverage_total += coverage
            if frame_count % 500 == 0:
                if expected_frame_count > 0:
                    percent = min(100.0, frame_count * 100.0 / expected_frame_count)
                    print(
                        f"Detecting subtitle glyphs: {frame_count}/{expected_frame_count} "
                        f"frames ({percent:.0f}%)...",
                        flush=True,
                    )
                else:
                    print(f"Detecting subtitle glyphs: {frame_count} frames...", flush=True)
    finally:
        capture.release()

    if frame_count == 0:
        raise RuntimeError(f"No frames were decoded from the ProPainter input video: {video_path}")
    _validate_frame_count(frame_count, expected_frame_count)
    return frame_count, coverage_total / frame_count


def _validate_frame_count(decoded_frame_count: int, expected_frame_count: int) -> None:
    if expected_frame_count > 0 and decoded_frame_count != expected_frame_count:
        raise RuntimeError(
            "Subtitle mask generation decoded "
            f"{decoded_frame_count}/{expected_frame_count} video frames. "
            "The processing video may be incomplete or damaged."
        )


def main() -> int:
    args = _parse_args()
    masks = tuple(
        (
            tuple(round(value) for value in raw[:4]),
            float(raw[4]),
            None if raw[5] < 0 else float(raw[5]),
        )
        for raw in (args.mask or [])
    )
    try:
        frame_count, average_coverage = generate_masks(
            args.video,
            args.output,
            tuple(args.roi) if args.roi is not None else None,
            masks=masks,
            time_offset=args.time_offset,
        )
    except Exception as exc:
        print(f"Dynamic subtitle mask generation failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Generated {frame_count} frame-wise subtitle masks "
        f"({average_coverage * 100:.1f}% average selected-area coverage).",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
