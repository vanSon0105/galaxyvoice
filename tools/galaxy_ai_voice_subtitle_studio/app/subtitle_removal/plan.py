from __future__ import annotations

from dataclasses import dataclass


Region = tuple[int, int, int, int]
MAX_REMOVAL_MASKS = 12


@dataclass(frozen=True)
class RemovalMask:
    mask_id: str
    name: str
    region: Region
    start_seconds: float = 0.0
    end_seconds: float | None = None

    def is_active(self, timestamp_seconds: float) -> bool:
        return self.start_seconds <= timestamp_seconds and (
            self.end_seconds is None or timestamp_seconds <= self.end_seconds
        )


@dataclass(frozen=True)
class RegionPreset:
    code: str
    name: str
    region: Region


REGION_PRESETS = (
    RegionPreset("bottom", "Phụ đề dưới", (5, 75, 90, 20)),
    RegionPreset("lower_third", "Dải chữ dưới", (8, 62, 84, 26)),
    RegionPreset("top", "Phụ đề trên", (5, 5, 90, 20)),
)


def validate_masks(
    masks: tuple[RemovalMask, ...],
    duration_seconds: float | None = None,
) -> tuple[RemovalMask, ...]:
    if not masks:
        raise ValueError("At least one subtitle-removal mask is required.")
    if len(masks) > MAX_REMOVAL_MASKS:
        raise ValueError(f"At most {MAX_REMOVAL_MASKS} subtitle-removal masks are supported.")

    identifiers: set[str] = set()
    for mask in masks:
        identifier = mask.mask_id.strip()
        if not identifier or identifier in identifiers:
            raise ValueError("Each subtitle-removal mask needs a unique ID.")
        identifiers.add(identifier)
        if not mask.name.strip():
            raise ValueError("Each subtitle-removal mask needs a name.")
        _validate_region(mask.region)
        if mask.start_seconds < 0:
            raise ValueError("A mask start time cannot be negative.")
        if mask.end_seconds is not None and mask.end_seconds <= mask.start_seconds:
            raise ValueError("A mask end time must be after its start time.")
        if duration_seconds is not None:
            if mask.start_seconds >= duration_seconds:
                raise ValueError("A mask start time must be inside the video duration.")
            if mask.end_seconds is not None and mask.end_seconds > duration_seconds:
                raise ValueError("A mask end time cannot exceed the video duration.")
    return masks


def mask_union_region(masks: tuple[RemovalMask, ...]) -> Region:
    validate_masks(masks)
    left = min(mask.region[0] for mask in masks)
    top = min(mask.region[1] for mask in masks)
    right = max(mask.region[0] + mask.region[2] for mask in masks)
    bottom = max(mask.region[1] + mask.region[3] for mask in masks)
    return left, top, right - left, bottom - top


def quality_warnings(
    mode: str,
    masks: tuple[RemovalMask, ...],
) -> list[str]:
    warnings: list[str] = []
    if mode == "blur":
        warnings.append(
            "Blur hides text but also softens the background inside every active mask."
        )
    elif mode == "fill":
        warnings.append(
            "Smart fill estimates pixels from mask edges and may leave artifacts on moving backgrounds."
        )
    if mode != "strip" and masks:
        if any(mask.region[2] * mask.region[3] >= 3_500 for mask in masks):
            warnings.append(
                "A large mask covers at least 35% of the frame and can noticeably reduce image quality."
            )
        if _has_overlapping_masks(masks):
            warnings.append(
                "Overlapping masks are active at the same time; their cleanup effects can accumulate."
            )
    return warnings


def _validate_region(region: Region) -> None:
    x, y, width, height = region
    if x < 0 or y < 0 or width < 1 or height < 1 or x + width > 100 or y + height > 100:
        raise ValueError("The selected subtitle area must fit inside the video.")


def _has_overlapping_masks(masks: tuple[RemovalMask, ...]) -> bool:
    for index, left in enumerate(masks):
        for right in masks[index + 1 :]:
            if _regions_overlap(left.region, right.region) and _ranges_overlap(left, right):
                return True
    return False


def _regions_overlap(left: Region, right: Region) -> bool:
    left_x, left_y, left_width, left_height = left
    right_x, right_y, right_width, right_height = right
    return (
        left_x < right_x + right_width
        and right_x < left_x + left_width
        and left_y < right_y + right_height
        and right_y < left_y + left_height
    )


def _ranges_overlap(left: RemovalMask, right: RemovalMask) -> bool:
    left_end = float("inf") if left.end_seconds is None else left.end_seconds
    right_end = float("inf") if right.end_seconds is None else right.end_seconds
    return left.start_seconds < right_end and right.start_seconds < left_end
