from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrameProbe:
    frame_index: int
    timestamp_ms: int
    signature: bytes
    text_activity: float = 0.0


@dataclass(frozen=True)
class ProbeRun:
    probes: tuple[FrameProbe, ...]


def signature_distance(first: bytes, second: bytes) -> int:
    if not first or not second or len(first) != len(second):
        return 10_000
    return sum((left ^ right).bit_count() for left, right in zip(first, second, strict=True))


def group_probes(
    probes: tuple[FrameProbe, ...],
    *,
    change_threshold: int,
    maximum_run_ms: int,
) -> tuple[ProbeRun, ...]:
    if change_threshold < 0:
        raise ValueError("change_threshold cannot be negative")
    if maximum_run_ms < 1:
        raise ValueError("maximum_run_ms must be positive")

    ordered = sorted(probes, key=lambda item: (item.timestamp_ms, item.frame_index))
    groups: list[list[FrameProbe]] = []
    active: list[FrameProbe] = []
    for probe in ordered:
        changed = bool(active) and signature_distance(active[-1].signature, probe.signature) > change_threshold
        expired = bool(active) and probe.timestamp_ms - active[0].timestamp_ms > maximum_run_ms
        if active and (changed or expired):
            groups.append(active)
            active = []
        active.append(probe)
    if active:
        groups.append(active)
    return tuple(ProbeRun(tuple(group)) for group in groups)


def representative_probes(run: ProbeRun, *, accurate: bool) -> tuple[FrameProbe, ...]:
    if not run.probes:
        return ()
    strongest = max(run.probes, key=lambda item: (item.text_activity, -item.timestamp_ms))
    if not accurate or len(run.probes) < 2:
        return (strongest,)
    selected = {run.probes[0].frame_index: run.probes[0], strongest.frame_index: strongest, run.probes[-1].frame_index: run.probes[-1]}
    return tuple(sorted(selected.values(), key=lambda item: item.frame_index))


def rescue_probe(run: ProbeRun, *, excluded_frame_indices: set[int]) -> FrameProbe | None:
    remaining = [probe for probe in run.probes if probe.frame_index not in excluded_frame_indices]
    if not remaining:
        return None
    return max(remaining, key=lambda item: (item.text_activity, -item.timestamp_ms))
