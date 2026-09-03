from __future__ import annotations

import tempfile
import wave
from dataclasses import replace
from pathlib import Path

from app.studio.models import StudioGenerationSpec, StudioVoiceSelection
from app.studio.render_cache import SpeechRenderCache


def _spec(text: str = "Xin chao") -> StudioGenerationSpec:
    return StudioGenerationSpec(
        project_id="project-1",
        title="Speech",
        text=text,
        engine_id="omnivoice",
        language="vi",
        output_dir="ignored",
        model_id="k2-fsa/OmniVoice",
        device="cpu",
        speed=1.0,
        formats=("wav",),
        voice=StudioVoiceSelection(source="profile", profile_id="son"),
        engine_options={"num_step": 32},
    )


def test_cache_key_normalizes_text_and_invalidates_voice_or_settings() -> None:
    cache = SpeechRenderCache(Path("cache"))
    base = _spec("  Xin   chao\r\nban  ")

    assert cache.key_for(base, voice_revision=2) == cache.key_for(
        _spec("Xin chao ban"), voice_revision=2
    )
    assert cache.key_for(base, voice_revision=2) != cache.key_for(base, voice_revision=3)
    assert cache.key_for(base, voice_revision=2) != cache.key_for(
        replace(base, speed=1.1), voice_revision=2
    )
    assert cache.key_for(base, voice_revision=2, context_text="cau truoc") != cache.key_for(
        base, voice_revision=2, context_text="cau khac"
    )


def test_cache_materializes_a_stored_render_without_exposing_cache_path() -> None:
    with tempfile.TemporaryDirectory(prefix="galaxy_speech_cache_") as temp_dir:
        root = Path(temp_dir)
        source = root / "source.wav"
        _write_wav(source)
        destination = root / "job" / "voice.wav"
        cache = SpeechRenderCache(root / "cache")
        key = cache.key_for(_spec(), voice_revision=1)

        assert cache.store(key, source) is True
        assert cache.restore(key, destination) is True
        assert destination.read_bytes() == source.read_bytes()
        assert destination.resolve().is_relative_to((root / "job").resolve())


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(1_000)
        output.writeframes((12_000).to_bytes(2, "little", signed=True) * 100)
