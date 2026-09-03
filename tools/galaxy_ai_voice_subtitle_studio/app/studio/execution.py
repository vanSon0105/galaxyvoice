from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .models import StudioGenerationSpec


DEFAULT_SPEECH_WORKERS = 3
MIN_SPEECH_WORKERS = 1
MAX_SPEECH_WORKERS = 8
PREWARM_ITEM_THRESHOLD = 3
DEFAULT_PERSIST_INTERVAL_SECONDS = 1.0


def clamp_speech_workers(value: int) -> int:
    return max(MIN_SPEECH_WORKERS, min(MAX_SPEECH_WORKERS, int(value)))


def speech_worker_count(engine: object, requested: int, item_count: int) -> int:
    engine_limit = max(1, int(getattr(engine, "max_parallelism", 1)))
    return min(clamp_speech_workers(requested), engine_limit, max(1, item_count))


def prewarm_engine(
    engine: object,
    spec: StudioGenerationSpec,
    item_count: int,
    progress: Callable[[str], None] | None = None,
) -> None:
    if item_count < PREWARM_ITEM_THRESHOLD:
        return
    prewarm = getattr(engine, "prewarm", None)
    if callable(prewarm):
        prewarm(spec, progress)


@dataclass
class IntervalGate:
    interval_seconds: float = DEFAULT_PERSIST_INTERVAL_SECONDS
    clock: Callable[[], float] = time.monotonic
    _last_run: float = field(init=False)

    def __post_init__(self) -> None:
        self._last_run = self.clock()

    def ready(self, *, force: bool = False) -> bool:
        now = self.clock()
        if not force and now - self._last_run < self.interval_seconds:
            return False
        self._last_run = now
        return True
