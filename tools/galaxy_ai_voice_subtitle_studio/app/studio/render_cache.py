from __future__ import annotations

import os
import shutil
import tempfile
import wave
from dataclasses import asdict
from pathlib import Path

from ..common.cache import read_json, stable_digest, write_json_atomic
from ..voice.text_splitter import normalize_text
from .models import StudioGenerationSpec


SPEECH_RENDER_CACHE_SCHEMA = 1


class SpeechRenderCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def key_for(
        self,
        spec: StudioGenerationSpec,
        *,
        voice_revision: int,
        context_text: str = "",
        context_index: int = 0,
    ) -> str:
        return stable_digest(
            {
                "schema": SPEECH_RENDER_CACHE_SCHEMA,
                "text": normalize_text(spec.text),
                "context": normalize_text(context_text),
                "context_index": max(0, int(context_index)),
                "voice_revision": max(1, int(voice_revision)),
                "engine_id": spec.engine_id,
                "model_id": spec.model_id,
                "device": spec.device,
                "language": spec.language,
                "speed": float(spec.speed),
                "duration": spec.duration,
                "voice": asdict(spec.voice),
                "engine_options": spec.engine_options,
            }
        )

    def restore(self, key: str, destination: Path) -> bool:
        if not self.contains(key):
            return False
        source = self._entry_dir(key) / "voice.wav"
        try:
            _copy_atomic(source, destination)
        except OSError:
            destination.unlink(missing_ok=True)
            return False
        return True

    def contains(self, key: str) -> bool:
        entry = self._entry_dir(key)
        source = entry / "voice.wav"
        metadata = read_json(entry / "manifest.json")
        try:
            return (
                isinstance(metadata, dict)
                and metadata.get("schema") == SPEECH_RENDER_CACHE_SCHEMA
                and metadata.get("key") == key
                and source.is_file()
                and source.stat().st_size > 0
                and _is_readable_wav(source)
            )
        except OSError:
            return False

    def store(self, key: str, source: Path) -> bool:
        try:
            valid_source = (
                source.is_file()
                and source.stat().st_size > 0
                and _is_readable_wav(source)
            )
        except OSError:
            valid_source = False
        if not valid_source:
            return False
        entry = self._entry_dir(key)
        try:
            entry.mkdir(parents=True, exist_ok=True)
            _copy_atomic(source, entry / "voice.wav")
            write_json_atomic(
                entry / "manifest.json",
                {"schema": SPEECH_RENDER_CACHE_SCHEMA, "key": key},
            )
        except OSError:
            return False
        return True

    def _entry_dir(self, key: str) -> Path:
        return self.root / key[:2] / key


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _is_readable_wav(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as source:
            return source.getnframes() > 0 and source.getframerate() > 0
    except (OSError, EOFError, wave.Error):
        return False
