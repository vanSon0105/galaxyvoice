from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.omnivoice.workspaces.gallery import list_voice_archetypes
from app.omnivoice.workspaces.longform import (
    LongformPlan,
    LongformSpan,
    PAUSE_SPAN,
    SPEECH_SPAN,
    detect_longform_workspace_kind,
    parse_audiobook_script,
    parse_story_script,
    plan_dubbing_cues,
)
from app.omnivoice.models import AUTO_MODE, OmniVoiceGenerationOptions
from app.omnivoice.workspaces.renderer import (
    _convert_to_mp3,
    _convert_to_m4b,
    _master_longform_wav,
    find_resumable_workspace_jobs,
    render_longform_plan,
)
from app.voice.srt import SubtitleCue, parse_srt


class _WorkspaceClient:
    def __init__(self, fail_on_request: int = 0) -> None:
        self.request_count = 0
        self.fail_on_request = fail_on_request

    def request(
        self,
        _command: str,
        payload: dict[str, object],
        **_kwargs: object,
    ) -> dict[str, object]:
        self.request_count += 1
        if self.request_count == self.fail_on_request:
            raise RuntimeError("simulated interruption")
        output = Path(str(payload["output_path"]))
        output.parent.mkdir(parents=True, exist_ok=True)
        duration = float(payload.get("duration") or 0.1)
        with wave.open(str(output), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(24_000)
            target.writeframes(b"\x01\x00" * round(24_000 * duration))
        return {"output_path": str(output)}


class LongformWorkspaceTests(unittest.TestCase):
    def test_mp3_export_embeds_title_author_and_cover(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wav_path = root / "book.wav"
            cover_path = root / "cover.jpg"
            wav_path.write_bytes(b"wav")
            cover_path.write_bytes(b"jpg")
            with (
                mock.patch(
                    "app.omnivoice.workspaces.renderer.find_ffmpeg",
                    return_value="ffmpeg",
                ),
                mock.patch(
                    "app.omnivoice.workspaces.renderer.subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stderr=""),
                ) as run,
            ):
                converted, _message = _convert_to_mp3(
                    wav_path,
                    root / "book.mp3",
                    title="Book",
                    author="Author",
                    cover_path=cover_path,
                )

            command = run.call_args.args[0]
            self.assertTrue(converted)
            self.assertIn("title=Book", command)
            self.assertIn("artist=Author", command)
            self.assertIn("attached_pic", command)

    def test_inline_spans_have_no_implicit_gap_and_use_sequential_srt_indices(self) -> None:
        plan = LongformPlan(
            spans=(
                LongformSpan(SPEECH_SPAN, "One", source_index=1, display_text="One"),
                LongformSpan(SPEECH_SPAN, "Two", source_index=1, display_text="Two"),
                LongformSpan(PAUSE_SPAN, pause_ms=200, source_index=1),
                LongformSpan(SPEECH_SPAN, "Three", source_index=1, display_text="Three"),
            ),
            chapters=(),
        )
        self.assertEqual(len(plan.spans), 4)

        with tempfile.TemporaryDirectory() as temp_dir:
            result = render_longform_plan(
                OmniVoiceGenerationOptions(
                    mode=AUTO_MODE,
                    text="unused",
                    output_dir=Path(temp_dir),
                    project_name="inline",
                ),
                plan,
                _WorkspaceClient(),
                gap_ms=500,
                export_mp3=False,
                project_document={
                    "chapters": [],
                    "language": "en",
                    "items": [],
                    "pronunciation_rules": [{"source": "AI", "replacement": "A I"}],
                },
            )

            cues = parse_srt(result.srt_path.read_text(encoding="utf-8"))
            self.assertEqual([cue.index for cue in cues], [1, 2, 3])
            with wave.open(str(result.wav_path), "rb") as rendered:
                duration_ms = round(rendered.getnframes() * 1000 / rendered.getframerate())
            self.assertLess(duration_ms, 1_000)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["document"]["pronunciation_rules"][0]["source"], "AI")

    def test_detects_story_dialogue_and_chaptered_audiobook(self) -> None:
        self.assertEqual(
            detect_longform_workspace_kind("# Mở đầu\nLan: Xin chào.\nMinh: Đi thôi."),
            "stories",
        )
        self.assertEqual(
            detect_longform_workspace_kind(
                "# Chương 1\n[voice:Narrator] Bắt đầu.\n# Chương 2\nTiếp tục."
            ),
            "audiobook",
        )

    def test_m4b_export_maps_cover_as_attached_picture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wav_path = root / "book.wav"
            cover_path = root / "cover.jpg"
            wav_path.write_bytes(b"wav")
            cover_path.write_bytes(b"jpg")
            with (
                mock.patch(
                    "app.omnivoice.workspaces.renderer.find_ffmpeg",
                    return_value="ffmpeg",
                ),
                mock.patch(
                    "app.omnivoice.workspaces.renderer.subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stderr=""),
                ) as run,
            ):
                converted, _message = _convert_to_m4b(
                    wav_path,
                    root / "book.m4b",
                    title="Book",
                    author="Author",
                    cover_path=cover_path,
                    chapters=[("One", 0, 1000)],
                )

            command = run.call_args.args[0]
            self.assertTrue(converted)
            self.assertIn(str(cover_path), command)
            self.assertIn("attached_pic", command)
            self.assertLess(command.index(str(cover_path)), command.index("-map_metadata"))

    def test_mastering_uses_bounded_loudnorm_and_atomically_replaces_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "combined.wav"
            wav_path.write_bytes(b"raw")

            def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
                Path(command[-1]).write_bytes(b"mastered")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                mock.patch("app.omnivoice.workspaces.renderer.find_ffmpeg", return_value="ffmpeg"),
                mock.patch("app.omnivoice.workspaces.renderer._run_command", side_effect=run) as runner,
            ):
                mastered, message = _master_longform_wav(
                    wav_path,
                    target_lufs=-40,
                    true_peak_db=0,
                )

            command = runner.call_args.args[0]
            self.assertTrue(mastered, message)
            self.assertEqual(wav_path.read_bytes(), b"mastered")
            self.assertIn("loudnorm=I=-24.0:TP=-0.1:LRA=11", command)

    def test_story_parser_supports_characters_pauses_and_prosody(self) -> None:
        plan = parse_story_script(
            "Narrator: Xin chào [pause 500ms]\nMara: [slow]Đi thôi[/slow]"
        )

        self.assertEqual(plan.voice_names, ("Narrator", "Mara"))
        self.assertEqual(
            [span.kind for span in plan.spans],
            [SPEECH_SPAN, PAUSE_SPAN, SPEECH_SPAN],
        )
        self.assertEqual(plan.spans[1].pause_ms, 500)
        self.assertEqual(plan.spans[2].voice_name, "Mara")
        self.assertEqual(plan.spans[2].speed, 0.85)

    def test_audiobook_parser_preserves_chapters_and_inline_voices(self) -> None:
        plan = parse_audiobook_script(
            "# Chương một\n[voice:Narrator] Mở đầu.\n\n"
            "# Chương hai\n[voice:Lan] Kết thúc."
        )

        self.assertEqual(plan.chapters, ("Chương một", "Chương hai"))
        speech = [span for span in plan.spans if span.kind == SPEECH_SPAN]
        self.assertEqual([span.chapter for span in speech], ["Chương một", "Chương hai"])
        self.assertEqual([span.voice_name for span in speech], ["Narrator", "Lan"])

    def test_dubbing_plan_preserves_original_timeline(self) -> None:
        plan = plan_dubbing_cues(
            [
                SubtitleCue(1, 1_000, 2_500, "Xin chào"),
                SubtitleCue(2, 3_000, 4_000, "Tạm biệt"),
            ]
        )

        self.assertEqual(plan.spans[0].kind, PAUSE_SPAN)
        self.assertEqual(plan.spans[0].pause_ms, 1_000)
        self.assertEqual(plan.spans[1].duration, 1.5)
        self.assertEqual(plan.spans[2].pause_ms, 500)
        self.assertEqual(plan.spans[3].duration, 1.0)

    def test_dubbing_renderer_fits_generated_audio_to_four_second_timeline(self) -> None:
        plan = plan_dubbing_cues(
            [
                SubtitleCue(1, 1_000, 2_500, "Xin chào"),
                SubtitleCue(2, 3_000, 4_000, "Tạm biệt"),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = render_longform_plan(
                OmniVoiceGenerationOptions(
                    mode=AUTO_MODE,
                    text="unused",
                    output_dir=Path(temp_dir),
                    project_name="dub-test",
                ),
                plan,
                _WorkspaceClient(),
                gap_ms=0,
                export_mp3=False,
                export_stems=True,
            )

            with wave.open(str(result.wav_path), "rb") as rendered:
                duration_ms = round(rendered.getnframes() * 1000 / rendered.getframerate())
            self.assertEqual(duration_ms, 4_000)
            self.assertTrue(result.srt_path.is_file())
            self.assertIsNotNone(result.stems_dir)
            self.assertEqual(len(list(result.stems_dir.glob("*.wav"))), 2)

    def test_failed_longform_job_resumes_without_regenerating_completed_spans(self) -> None:
        plan = parse_story_script("Lan: Câu một.\nMinh: Câu hai.")
        with tempfile.TemporaryDirectory() as temp_dir:
            options = OmniVoiceGenerationOptions(
                mode=AUTO_MODE,
                text="unused",
                output_dir=Path(temp_dir),
                project_name="resume-test",
            )
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                render_longform_plan(
                    options,
                    plan,
                    _WorkspaceClient(fail_on_request=2),
                    export_mp3=False,
                )

            jobs = find_resumable_workspace_jobs(Path(temp_dir))
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].status, "failed")
            resumed_client = _WorkspaceClient()
            result = render_longform_plan(
                options,
                plan,
                resumed_client,
                export_mp3=False,
                resume_project_dir=jobs[0].project_dir,
            )

            self.assertEqual(resumed_client.request_count, 1)
            self.assertTrue(result.wav_path.is_file())
            self.assertEqual(find_resumable_workspace_jobs(Path(temp_dir)), ())


class VoiceGalleryWorkspaceTests(unittest.TestCase):
    def test_gallery_contains_ready_to_use_valid_design_archetypes(self) -> None:
        archetypes = list_voice_archetypes()

        self.assertGreaterEqual(len(archetypes), 500)
        self.assertEqual(len({item.archetype_id for item in archetypes}), len(archetypes))
        self.assertTrue(all(item.instruct and item.sample_text for item in archetypes))


if __name__ == "__main__":
    unittest.main()
