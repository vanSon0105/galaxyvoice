from __future__ import annotations

from app.studio.execution import clamp_speech_workers, speech_worker_count


class _ParallelEngine:
    max_parallelism = 20


class _SerialEngine:
    max_parallelism = 1


def test_worker_count_is_clamped_to_public_bounds() -> None:
    assert clamp_speech_workers(0) == 1
    assert clamp_speech_workers(3) == 3
    assert clamp_speech_workers(99) == 8
    assert speech_worker_count(_ParallelEngine(), 99, 20) == 8


def test_engine_limit_can_force_serial_execution() -> None:
    assert speech_worker_count(_SerialEngine(), 8, 20) == 1
