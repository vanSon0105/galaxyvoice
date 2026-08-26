"""Fair, cooperative resource scheduling for local runtime jobs."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Mapping

from ..common.errors import TaskCancelledError


@dataclass(frozen=True)
class _Waiter:
    task_id: str
    resource_keys: tuple[str, ...]


class ResourceScheduler:
    def __init__(self, capacities: Mapping[str, int] | None = None) -> None:
        configured = dict(capacities or {"accelerator": 1, "network": 2})
        self._capacities = {key: max(1, int(value)) for key, value in configured.items()}
        self._used: dict[str, int] = {}
        self._active: dict[str, tuple[str, ...]] = {}
        self._waiting: list[_Waiter] = []
        self._condition = threading.Condition(threading.RLock())

    def _capacity(self, key: str) -> int:
        return self._capacities.get(key, 1)

    def _has_capacity(self, keys: tuple[str, ...]) -> bool:
        return all(self._used.get(key, 0) < self._capacity(key) for key in keys)

    def _has_earlier_conflict(self, waiter: _Waiter) -> bool:
        requested = set(waiter.resource_keys)
        for candidate in self._waiting:
            if candidate is waiter:
                return False
            if requested.intersection(candidate.resource_keys):
                return True
        return False

    @contextmanager
    def acquire(
        self,
        task_id: str,
        resource_keys: tuple[str, ...],
        stop_event: threading.Event,
        on_wait: Callable[[], None] | None = None,
    ) -> Iterator[None]:
        keys = tuple(dict.fromkeys(key for key in resource_keys if key))
        if not keys:
            if stop_event.is_set():
                raise TaskCancelledError()
            yield
            return

        waiter = _Waiter(task_id=task_id, resource_keys=keys)
        acquired = False
        with self._condition:
            self._waiting.append(waiter)
            waiting_reported = False
            try:
                while True:
                    if stop_event.is_set():
                        raise TaskCancelledError()
                    if self._has_capacity(keys) and not self._has_earlier_conflict(waiter):
                        self._waiting.remove(waiter)
                        for key in keys:
                            self._used[key] = self._used.get(key, 0) + 1
                        self._active[task_id] = keys
                        acquired = True
                        break
                    if not waiting_reported and on_wait is not None:
                        on_wait()
                        waiting_reported = True
                    self._condition.wait(timeout=0.1)
            except BaseException:
                if waiter in self._waiting:
                    self._waiting.remove(waiter)
                self._condition.notify_all()
                raise

        try:
            yield
        finally:
            if acquired:
                with self._condition:
                    active_keys = self._active.pop(task_id, keys)
                    for key in active_keys:
                        remaining = self._used.get(key, 0) - 1
                        if remaining > 0:
                            self._used[key] = remaining
                        else:
                            self._used.pop(key, None)
                    self._condition.notify_all()

    def wake(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            return {
                "capacities": dict(self._capacities),
                "used": dict(self._used),
                "active": dict(self._active),
                "waiting": [
                    {"task_id": waiter.task_id, "resource_keys": waiter.resource_keys}
                    for waiter in self._waiting
                ],
            }


def resource_keys_for_device(device: str) -> tuple[str, ...]:
    normalized = (device or "auto").strip().lower()
    if normalized in {"", "cpu"}:
        return ()
    return ("accelerator",)


shared_resource_scheduler = ResourceScheduler()
