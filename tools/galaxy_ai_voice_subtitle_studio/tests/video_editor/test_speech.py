from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from app.common.errors import TaskCancelledError
from app.studio.models import StudioArtifact, StudioGenerationSpec, StudioVoiceSelection
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


if __name__ == "__main__":
    unittest.main()
