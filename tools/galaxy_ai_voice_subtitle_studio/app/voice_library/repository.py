from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from ..common.cache import read_json, write_json_atomic
from .models import VoiceProfileRecord


class VoiceLibraryRepository:
    """Atomic metadata store; voice assets live beside this index."""

    _locks_guard = threading.Lock()
    _locks: dict[Path, threading.RLock] = {}

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = (self.root / "library.json").resolve()
        self.assets_dir = self.root / "voices"
        self.pins_dir = self.root / "project-pins"
        with self._locks_guard:
            self._lock = self._locks.setdefault(self.path, threading.RLock())

    def list(self) -> tuple[VoiceProfileRecord, ...]:
        payload = read_json(self.path)
        items = payload.get("voices", []) if isinstance(payload, dict) else []
        records = tuple(
            VoiceProfileRecord.from_payload(item)
            for item in items
            if isinstance(item, dict) and item.get("voice_id")
        )
        return tuple(sorted(records, key=lambda item: (not item.favorite, item.name.casefold())))

    def get(self, voice_id: str) -> VoiceProfileRecord | None:
        return next((item for item in self.list() if item.voice_id == voice_id), None)

    def save(self, record: VoiceProfileRecord) -> VoiceProfileRecord:
        with self._lock:
            records = list(self.list())
            existing = next((item for item in records if item.voice_id == record.voice_id), None)
            stored = replace(record, revision=(existing.revision + 1 if existing else max(1, record.revision)))
            records = [stored if item.voice_id == stored.voice_id else item for item in records]
            if existing is None:
                records.append(stored)
            self._write(records)
            return stored

    def delete(self, voice_id: str) -> VoiceProfileRecord | None:
        with self._lock:
            records = list(self.list())
            target = next((item for item in records if item.voice_id == voice_id), None)
            if target is not None:
                self._write([item for item in records if item.voice_id != voice_id])
            return target

    def _write(self, records: list[VoiceProfileRecord]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            self.path,
            {"version": 1, "voices": [item.to_payload() for item in records]},
        )
