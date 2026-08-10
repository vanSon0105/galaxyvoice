from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ...common.cache import read_json, write_json_atomic


@dataclass(frozen=True)
class TranscriptEntry:
    entry_id: str
    text: str
    language: str
    source_path: str
    source_srt: str
    translated_srt: str
    created_at: str


class TranscriptStore:
    def __init__(self, path: Path, *, limit: int = 200) -> None:
        self.path = Path(path)
        self.limit = max(1, int(limit))

    def list(self) -> tuple[TranscriptEntry, ...]:
        payload = read_json(self.path)
        if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
            return ()
        entries: list[TranscriptEntry] = []
        for item in payload["entries"]:
            if not isinstance(item, dict):
                continue
            entry_id = str(item.get("entry_id") or "").strip()
            text = str(item.get("text") or "").strip()
            if not entry_id or not text:
                continue
            entries.append(
                TranscriptEntry(
                    entry_id=entry_id,
                    text=text,
                    language=str(item.get("language") or "unknown"),
                    source_path=str(item.get("source_path") or ""),
                    source_srt=str(item.get("source_srt") or ""),
                    translated_srt=str(item.get("translated_srt") or ""),
                    created_at=str(item.get("created_at") or ""),
                )
            )
        return tuple(entries)

    def search(self, query: str) -> tuple[TranscriptEntry, ...]:
        needle = query.strip().casefold()
        if not needle:
            return self.list()
        return tuple(
            entry
            for entry in self.list()
            if needle in f"{entry.text} {entry.language} {entry.source_path}".casefold()
        )

    def add(
        self,
        *,
        text: str,
        language: str,
        source_path: str,
        source_srt: str = "",
        translated_srt: str = "",
    ) -> TranscriptEntry:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Transcript không có nội dung.")
        entry = TranscriptEntry(
            entry_id=uuid4().hex,
            text=cleaned,
            language=language.strip() or "unknown",
            source_path=source_path.strip(),
            source_srt=source_srt.strip(),
            translated_srt=translated_srt.strip(),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        entries = (entry, *self.list())[: self.limit]
        self._save(entries)
        return entry

    def delete(self, entry_id: str) -> None:
        self._save(tuple(entry for entry in self.list() if entry.entry_id != entry_id))

    def clear(self) -> None:
        self._save(())

    def _save(self, entries: tuple[TranscriptEntry, ...]) -> None:
        write_json_atomic(
            self.path,
            {"version": 1, "entries": [asdict(entry) for entry in entries]},
        )
