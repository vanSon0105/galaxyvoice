from __future__ import annotations

import tempfile
import threading
import time
import unittest
import wave
from dataclasses import replace
from pathlib import Path

from app.common.errors import TaskCancelledError
from app.studio.models import StudioArtifact, StudioGenerationSpec, StudioVoiceSelection
from app.studio.render_cache import SpeechRenderCache
from app.video_editor.speech import (
    EditorSpeechCueSpec,
    EditorSpeechService,
    EditorSpeechSpec,
)


class _FakeEngine:
    engine_id = "omnivoice"

    def __init__(self) -> None:
        self.generated: list[StudioGenerationSpec] = []

    def generate(self, spec: StudioGenerationSpec, progress=None) -> StudioArtifact:
        self.generated.append(spec)
        project_dir = Path(spec.output_dir) / spec.output_name
        project_dir.mkdir(parents=True)
        wav_path = project_dir / "voice.wav"
        wav_path.write_bytes(b"wav")
        manifest_path = project_dir / "manifest.json"
        manifest_path.write_text("{}", encoding="utf-8")
        return StudioArtifact(project_dir, wav_path, None, manifest_path)


class _ParallelEngine(_FakeEngine):
    max_parallelism = 8

    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0
        self.prewarm_calls = 0
        self.lock = threading.Lock()

    def prewarm(self, _spec: StudioGenerationSpec, _progress=None) -> None:
        self.prewarm_calls += 1

    def generate(self, spec: StudioGenerationSpec, progress=None) -> StudioArtifact:
        with self.lock:
            self.generated.append(spec)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.04)
            project_dir = Path(spec.output_dir) / spec.output_name
            project_dir.mkdir(parents=True)
            wav_path = project_dir / "voice.wav"
            wav_path.write_bytes(b"wav")
            manifest_path = project_dir / "manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            return StudioArtifact(project_dir, wav_path, None, manifest_path)
        finally:
            with self.lock:
                self.active -= 1


class _PcmEngine(_FakeEngine):
    def __init__(self, *, cluster_has_boundary: bool = True) -> None:
        super().__init__()
        self.cluster_has_boundary = cluster_has_boundary

    def generate(self, spec: StudioGenerationSpec, progress=None) -> StudioArtifact:
        self.generated.append(spec)
        project_dir = Path(spec.output_dir) / spec.output_name
        project_dir.mkdir(parents=True)
        wav_path = project_dir / "voice.wav"
        if "\n\n" in spec.text and self.cluster_has_boundary:
            _write_pcm_wav(wav_path, (300, 200, 500))
        else:
            _write_pcm_wav(wav_path, (500,))
        manifest_path = project_dir / "manifest.json"
        manifest_path.write_text("{}", encoding="utf-8")
        return StudioArtifact(project_dir, wav_path, None, manifest_path)


class EditorSpeechServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="galaxy_editor_speech_")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _spec(self) -> EditorSpeechSpec:
        return EditorSpeechSpec(
            job_id="editor-job-1",
            project_id="project-1",
            title="Editor speech",
            output_dir=str(self.root),
            engine_id="omnivoice",
            language="vi",
            voice=StudioVoiceSelection(source="profile", profile_id="son"),
            cues=(
                EditorSpeechCueSpec("item-1", "subtitle-1", "cue-1", 1_000, "Xin chao"),
                EditorSpeechCueSpec("item-2", "subtitle-1", "cue-2", 2_000, "Tam biet"),
            ),
        )

    def test_delivers_each_item_with_timeline_identity_before_job_finishes(self) -> None:
        delivered = []
        checkpoints = []
        engine = _FakeEngine()

        result = EditorSpeechService().execute(
            self._spec(),
            engine,
            progress=lambda _message, _value: None,
            checkpoint=checkpoints.append,
            item_finished=delivered.append,
        )

        self.assertEqual([item.item_id for item in delivered], ["item-1", "item-2"])
        self.assertEqual(delivered[0].track_id, "subtitle-1")
        self.assertEqual(delivered[0].cue_id, "cue-1")
        self.assertEqual(delivered[0].start_ms, 1_000)
        self.assertEqual(delivered[0].status, "done")
        self.assertTrue(Path(delivered[0].wav_path).is_file())
        self.assertEqual(result.completed_count, 2)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(checkpoints[-1]["completed"], 2)
        self.assertEqual([spec.output_name for spec in engine.generated], ["item-1", "item-2"])

    def test_stops_before_the_next_cue_when_cancelled(self) -> None:
        stop_event = threading.Event()
        engine = _FakeEngine()

        def cancel_after_first(item) -> None:
            if item.item_id == "item-1":
                stop_event.set()

        with self.assertRaises(TaskCancelledError):
            EditorSpeechService().execute(
                self._spec(),
                engine,
                stop_event=stop_event,
                item_finished=cancel_after_first,
            )

        self.assertEqual([spec.output_name for spec in engine.generated], ["item-1"])

    def test_parallel_safe_engine_uses_default_bound_and_prewarms_once(self) -> None:
        cues = tuple(
            EditorSpeechCueSpec(
                f"item-{index}", "subtitle-1", f"cue-{index}", index * 1_000, f"Line {index}"
            )
            for index in range(1, 7)
        )
        engine = _ParallelEngine()

        result = EditorSpeechService().execute(replace(self._spec(), cues=cues), engine)

        self.assertEqual(result.completed_count, 6)
        self.assertEqual(engine.max_active, 3)
        self.assertEqual(engine.prewarm_calls, 1)

    def test_short_cues_render_as_one_cluster_and_return_original_identities(self) -> None:
        engine = _PcmEngine()
        spec = replace(
            self._spec(),
            cues=(
                EditorSpeechCueSpec("item-1", "subtitle-1", "cue-1", 0, "Xin chao", end_ms=900),
                EditorSpeechCueSpec("item-2", "subtitle-1", "cue-2", 1_050, "Tam biet", end_ms=2_000),
            ),
        )

        result = EditorSpeechService().execute(spec, engine)

        self.assertEqual(len(engine.generated), 1)
        self.assertIn("\n\n", engine.generated[0].text)
        self.assertEqual([item.item_id for item in result.items], ["item-1", "item-2"])
        self.assertTrue(all(Path(item.wav_path).is_file() for item in result.items))
        self.assertEqual(result.items[0].cue_duration_ms, 900)
        self.assertGreater(result.items[0].audio_duration_ms, 0)
        self.assertIn(result.items[0].fit_status, {"fits", "speed-up", "condense"})

    def test_cluster_without_proven_boundaries_falls_back_to_individual_cues(self) -> None:
        engine = _PcmEngine(cluster_has_boundary=False)
        spec = replace(
            self._spec(),
            cues=(
                EditorSpeechCueSpec("item-1", "subtitle-1", "cue-1", 0, "Xin chao", end_ms=900),
                EditorSpeechCueSpec("item-2", "subtitle-1", "cue-2", 1_050, "Tam biet", end_ms=2_000),
            ),
        )

        result = EditorSpeechService().execute(spec, engine)

        self.assertEqual(len(engine.generated), 3)
        self.assertEqual(result.completed_count, 2)

    def test_render_cache_reuses_audio_and_invalidates_voice_revision(self) -> None:
        engine = _PcmEngine()
        cache = SpeechRenderCache(self.root / "cache")
        service = EditorSpeechService(render_cache=cache)
        single = replace(self._spec(), cues=(self._spec().cues[0],), voice_revision=1)

        first = service.execute(single, engine)
        second = service.execute(single, engine)
        third = service.execute(replace(single, voice_revision=2), engine)

        self.assertEqual(len(engine.generated), 2)
        self.assertTrue(Path(first.items[0].wav_path).is_file())
        self.assertTrue(Path(second.items[0].wav_path).is_file())
        self.assertTrue(Path(third.items[0].wav_path).is_file())

    def test_unreadable_timing_metadata_does_not_discard_generated_audio(self) -> None:
        engine = _FakeEngine()
        cue = EditorSpeechCueSpec(
            "item-1",
            "subtitle-1",
            "cue-1",
            0,
            "Xin chao",
            end_ms=1_000,
        )

        result = EditorSpeechService().execute(replace(self._spec(), cues=(cue,)), engine)

        self.assertEqual(result.completed_count, 1)
        self.assertEqual(result.items[0].fit_status, "unmeasured")
        self.assertIn("Không đo được độ vừa", result.items[0].warnings[0])

    def test_cluster_cache_restores_every_cue_without_rendering_the_context_again(self) -> None:
        engine = _PcmEngine()
        service = EditorSpeechService(render_cache=SpeechRenderCache(self.root / "cache"))
        spec = replace(
            self._spec(),
            cues=(
                EditorSpeechCueSpec("item-1", "subtitle-1", "cue-1", 0, "Xin chao", end_ms=900),
                EditorSpeechCueSpec("item-2", "subtitle-1", "cue-2", 1_050, "Tam biet", end_ms=2_000),
            ),
        )

        first = service.execute(spec, engine)
        second = service.execute(spec, engine)

        self.assertEqual(len(engine.generated), 1)
        self.assertTrue(all(Path(item.wav_path).is_file() for item in first.items))
        self.assertTrue(all(Path(item.wav_path).is_file() for item in second.items))


def _write_pcm_wav(path: Path, durations_ms: tuple[int, ...]) -> None:
    frames = bytearray()
    for index, duration_ms in enumerate(durations_ms):
        sample = (12_000 if index % 2 == 0 else 0).to_bytes(2, "little", signed=True)
        frames.extend(sample * duration_ms)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(1_000)
        handle.writeframes(frames)


if __name__ == "__main__":
    unittest.main()
