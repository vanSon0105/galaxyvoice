from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.cache import stable_digest  # noqa: E402
from app.srt import SubtitleCue  # noqa: E402
from app.transcription import (  # noqa: E402
    VideoSubtitleDraft,
    VideoSubtitleOptions,
    create_subtitles_from_video,
    export_subtitle_package,
    prepare_subtitles_from_video,
    transcribe_with_faster_whisper,
)


def _draft_for_export(audio_path: Path) -> VideoSubtitleDraft:
    source_cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hello.")
    translated_cue = SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Xin chao.")
    return VideoSubtitleDraft(
        source_video=Path("clip.mp4"),
        project_name="clip",
        audio_path=audio_path,
        source_language="en",
        target_language="vi",
        whisper_model="base",
        ai_provider="deepseek",
        ai_model="deepseek-v4-flash",
        ai_base_url="https://api.deepseek.com",
        source_cues=(source_cue,),
        translated_cues=(translated_cue,),
        warnings=[],
    )


class TranscriptionTests(unittest.TestCase):
    def test_faster_whisper_uses_cuda_when_available(self) -> None:
        model_calls: list[tuple[str, str, str]] = []

        class FakeWhisperModel:
            def __init__(self, model_size: str, device: str, compute_type: str) -> None:
                model_calls.append((model_size, device, compute_type))

            def transcribe(self, *_args, **_kwargs):
                return iter(()), object()

        modules = {
            "ctranslate2": types.SimpleNamespace(get_cuda_device_count=lambda: 1),
            "faster_whisper": types.SimpleNamespace(WhisperModel=FakeWhisperModel),
        }
        progress: list[str] = []
        with patch.dict(sys.modules, modules):
            cues = transcribe_with_faster_whisper(Path("speech.wav"), None, "base", progress.append)

        self.assertEqual(cues, [])
        self.assertEqual(model_calls, [("base", "cuda", "float16")])
        self.assertTrue(any("CUDA" in message for message in progress))

    def test_faster_whisper_falls_back_to_cpu_when_cuda_initialization_fails(self) -> None:
        model_calls: list[tuple[str, str, str]] = []

        class FakeWhisperModel:
            def __init__(self, model_size: str, device: str, compute_type: str) -> None:
                model_calls.append((model_size, device, compute_type))
                if device == "cuda":
                    raise RuntimeError("missing CUDA runtime")

            def transcribe(self, *_args, **_kwargs):
                return iter(()), object()

        modules = {
            "ctranslate2": types.SimpleNamespace(get_cuda_device_count=lambda: 1),
            "faster_whisper": types.SimpleNamespace(WhisperModel=FakeWhisperModel),
        }
        progress: list[str] = []
        with patch.dict(sys.modules, modules):
            cues = transcribe_with_faster_whisper(Path("speech.wav"), None, "base", progress.append)

        self.assertEqual(cues, [])
        self.assertEqual(
            model_calls,
            [("base", "cuda", "float16"), ("base", "cpu", "int8")],
        )
        self.assertTrue(any("Falling back to CPU" in message for message in progress))

    def test_faster_whisper_falls_back_to_cpu_when_cuda_fails_during_iteration(self) -> None:
        model_calls: list[tuple[str, str, str]] = []

        class FakeWhisperModel:
            def __init__(self, model_size: str, device: str, compute_type: str) -> None:
                model_calls.append((model_size, device, compute_type))
                self.device = device

            def transcribe(self, *_args, **_kwargs):
                if self.device == "cuda":
                    def failing_segments():
                        raise RuntimeError("CUDA execution failed")
                        yield

                    return failing_segments(), object()
                return iter(
                    [types.SimpleNamespace(text="Hello.", start=0.0, end=1.0)]
                ), object()

        modules = {
            "ctranslate2": types.SimpleNamespace(get_cuda_device_count=lambda: 1),
            "faster_whisper": types.SimpleNamespace(WhisperModel=FakeWhisperModel),
        }
        progress: list[str] = []
        with patch.dict(sys.modules, modules):
            cues = transcribe_with_faster_whisper(Path("speech.wav"), None, "base", progress.append)

        self.assertEqual([cue.text for cue in cues], ["Hello."])
        self.assertEqual(
            model_calls,
            [("base", "cuda", "float16"), ("base", "cpu", "int8")],
        )
        self.assertTrue(any("Falling back to CPU" in message for message in progress))

    def test_prepare_subtitles_reuses_cached_transcription_for_the_same_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"fake video")
            transcribe_count = 0
            progress_messages: list[str] = []

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                Path(command[-1]).write_bytes(b"fake audio")
                return subprocess.CompletedProcess(command, 0, "", "")

            def transcriber(_audio_path, _language, _model, _progress):
                nonlocal transcribe_count
                transcribe_count += 1
                return [SubtitleCue(index=1, start_ms=0, end_ms=1200, text="Cached speech.")]

            options = VideoSubtitleOptions(
                video_path=video,
                output_dir=root / "exports",
                source_language="en",
                target_language="none",
                cache_dir=root / "cache",
            )
            first = prepare_subtitles_from_video(
                options,
                progress=progress_messages.append,
                ffmpeg_path="ffmpeg",
                runner=runner,
                transcriber=transcriber,
            )
            first.cleanup()
            second = prepare_subtitles_from_video(
                options,
                progress=progress_messages.append,
                ffmpeg_path="ffmpeg",
                runner=runner,
                transcriber=transcriber,
            )
            try:
                self.assertEqual(transcribe_count, 1)
                self.assertEqual(second.source_cues[0].text, "Cached speech.")
                self.assertTrue(second.audio_path.exists())
                self.assertTrue(any("cached transcription" in message.lower() for message in progress_messages))
            finally:
                second.cleanup()

    def test_prepare_subtitles_invalidates_cache_when_video_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"first video")
            transcribe_count = 0

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                Path(command[-1]).write_bytes(b"fake audio")
                return subprocess.CompletedProcess(command, 0, "", "")

            def transcriber(_audio_path, _language, _model, _progress):
                nonlocal transcribe_count
                transcribe_count += 1
                return [SubtitleCue(index=1, start_ms=0, end_ms=1200, text="Fresh speech.")]

            options = VideoSubtitleOptions(
                video_path=video,
                output_dir=root / "exports",
                source_language="en",
                target_language="none",
                cache_dir=root / "cache",
            )
            first = prepare_subtitles_from_video(
                options,
                ffmpeg_path="ffmpeg",
                runner=runner,
                transcriber=transcriber,
            )
            first.cleanup()
            video.write_bytes(b"second video with different size")
            second = prepare_subtitles_from_video(
                options,
                ffmpeg_path="ffmpeg",
                runner=runner,
                transcriber=transcriber,
            )
            try:
                self.assertEqual(transcribe_count, 2)
            finally:
                second.cleanup()

    def test_prepare_subtitles_invalidates_cache_when_same_size_video_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"first-video")
            original_stat = video.stat()
            transcribe_count = 0

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                Path(command[-1]).write_bytes(b"fake audio")
                return subprocess.CompletedProcess(command, 0, "", "")

            def transcriber(_audio_path, _language, _model, _progress):
                nonlocal transcribe_count
                transcribe_count += 1
                return [SubtitleCue(index=1, start_ms=0, end_ms=1200, text="Fresh speech.")]

            options = VideoSubtitleOptions(
                video_path=video,
                output_dir=root / "exports",
                source_language="en",
                target_language="none",
                cache_dir=root / "cache",
            )
            first = prepare_subtitles_from_video(
                options,
                ffmpeg_path="ffmpeg",
                runner=runner,
                transcriber=transcriber,
            )
            first.cleanup()
            video.write_bytes(b"other-video")
            os.utime(video, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            second = prepare_subtitles_from_video(
                options,
                ffmpeg_path="ffmpeg",
                runner=runner,
                transcriber=transcriber,
            )
            try:
                self.assertEqual(transcribe_count, 2)
            finally:
                second.cleanup()

    def test_prepare_subtitles_does_not_migrate_a_legacy_cache_without_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_dir = root / "cache"
            video = root / "clip.mp4"
            video.write_bytes(b"first-video")
            original_stat = video.stat()
            legacy_digest = stable_digest(
                {
                    "version": 1,
                    "video_path": str(video.resolve()),
                    "video_size": original_stat.st_size,
                    "video_mtime_ns": original_stat.st_mtime_ns,
                    "source_language": "en",
                    "whisper_model": "base",
                }
            )
            legacy_path = cache_dir / "transcriptions" / f"{legacy_digest}.json"
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "cues": [
                            {"index": 1, "start_ms": 0, "end_ms": 1000, "text": "Stale speech."}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            video.write_bytes(b"other-video")
            os.utime(video, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            transcribe_count = 0

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                Path(command[-1]).write_bytes(b"fake audio")
                return subprocess.CompletedProcess(command, 0, "", "")

            def transcriber(_audio_path, _language, _model, _progress):
                nonlocal transcribe_count
                transcribe_count += 1
                return [SubtitleCue(index=1, start_ms=0, end_ms=1200, text="Fresh speech.")]

            draft = prepare_subtitles_from_video(
                VideoSubtitleOptions(
                    video_path=video,
                    output_dir=root / "exports",
                    source_language="en",
                    target_language="none",
                    cache_dir=cache_dir,
                ),
                ffmpeg_path="ffmpeg",
                runner=runner,
                transcriber=transcriber,
            )
            try:
                self.assertEqual(transcribe_count, 1)
                self.assertEqual(draft.source_cues[0].text, "Fresh speech.")
            finally:
                draft.cleanup()

    def test_prepare_subtitles_keeps_output_folder_empty_until_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            output_dir = root / "exports"
            video.write_bytes(b"fake video")

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                Path(command[-1]).write_bytes(b"fake audio")
                return subprocess.CompletedProcess(command, 0, "", "")

            def transcriber(_audio_path, _language, _model, _progress):
                return [SubtitleCue(index=1, start_ms=0, end_ms=1200, text="Hello.")]

            def translator(cues, _options):
                return [
                    SubtitleCue(index=cue.index, start_ms=cue.start_ms, end_ms=cue.end_ms, text="Xin chao.")
                    for cue in cues
                ]

            draft = prepare_subtitles_from_video(
                VideoSubtitleOptions(
                    video_path=video,
                    output_dir=output_dir,
                    project_name="clip",
                    source_language="en",
                    target_language="vi",
                    ai_api_key="test-key",
                ),
                ffmpeg_path="ffmpeg",
                runner=runner,
                transcriber=transcriber,
                translator=translator,
            )
            try:
                self.assertFalse(output_dir.exists())
                self.assertTrue(draft.audio_path.exists())
                self.assertIn("Hello.", draft.source_srt_text)
                self.assertIn("Xin chao.", draft.translated_srt_text)
                self.assertEqual(draft.script_text, "Xin chao.")
            finally:
                draft.cleanup()

    def test_export_subtitle_package_preserves_existing_file_names_and_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"fake video")

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                Path(command[-1]).write_bytes(b"fake audio")
                return subprocess.CompletedProcess(command, 0, "", "")

            def transcriber(_audio_path, _language, _model, _progress):
                return [SubtitleCue(index=1, start_ms=0, end_ms=1200, text="Hello.")]

            def translator(cues, _options):
                return [
                    SubtitleCue(index=cue.index, start_ms=cue.start_ms, end_ms=cue.end_ms, text="Xin chao.")
                    for cue in cues
                ]

            draft = prepare_subtitles_from_video(
                VideoSubtitleOptions(
                    video_path=video,
                    output_dir=root / "unused",
                    project_name="clip",
                    source_language="en",
                    target_language="vi",
                    ai_api_key="test-key",
                ),
                ffmpeg_path="ffmpeg",
                runner=runner,
                transcriber=transcriber,
                translator=translator,
            )
            try:
                result = export_subtitle_package(draft, root / "exports", "clip")

                self.assertEqual(result.project_dir.name, "clip")
                self.assertEqual(result.audio_path.name, "clip_speech.wav")
                self.assertEqual(result.source_srt_path.name, "clip_original.srt")
                self.assertEqual(result.translated_srt_path.name, "clip_vi.srt")
                self.assertEqual(result.manifest_path.name, "subtitle_manifest.json")
                self.assertEqual(
                    result.source_srt_path.read_text(encoding="utf-8"),
                    "1\n00:00:00,000 --> 00:00:01,200\nHello.\n",
                )
                self.assertEqual(
                    result.translated_srt_path.read_text(encoding="utf-8"),
                    "1\n00:00:00,000 --> 00:00:01,200\nXin chao.\n",
                )
                manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["files"]["audio"], "clip_speech.wav")
                self.assertEqual(manifest["files"]["source_srt"], "clip_original.srt")
                self.assertEqual(manifest["files"]["translated_srt"], "clip_vi.srt")
            finally:
                draft.cleanup()

    def test_export_uses_edited_srt_for_cue_count_and_script_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio = root / "speech.wav"
            audio.write_bytes(b"fake audio")
            draft = _draft_for_export(audio)
            source_text = (
                "1\n00:00:00,000 --> 00:00:01,000\nHello.\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nWorld.\n"
            )
            translated_text = (
                "1\n00:00:00,000 --> 00:00:01,000\nXin chao.\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nThe gioi.\n"
            )

            result = export_subtitle_package(
                draft,
                root / "exports",
                "clip",
                source_srt_text=source_text,
                translated_srt_text=translated_text,
            )

            self.assertEqual(result.cue_count, 2)
            self.assertEqual(result.script_text, "Xin chao.\nThe gioi.")
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["cue_count"], 2)

    def test_failed_export_removes_the_incomplete_project_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio = root / "speech.wav"
            audio.write_bytes(b"fake audio")
            draft = _draft_for_export(audio)
            output_dir = root / "exports"

            with patch("app.transcription.shutil.copy2", side_effect=OSError("copy failed")):
                with self.assertRaisesRegex(OSError, "copy failed"):
                    export_subtitle_package(draft, output_dir, "clip")

            self.assertEqual(list(output_dir.iterdir()), [])

    def test_failed_export_reports_when_incomplete_folder_cannot_be_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio = root / "speech.wav"
            audio.write_bytes(b"fake audio")
            draft = _draft_for_export(audio)

            with (
                patch("app.transcription.shutil.copy2", side_effect=OSError("copy failed")),
                patch("app.transcription.shutil.rmtree", side_effect=PermissionError("folder locked")),
            ):
                with self.assertRaisesRegex(RuntimeError, "folder locked"):
                    export_subtitle_package(draft, root / "exports", "clip")

    def test_create_subtitles_from_video_writes_original_and_translated_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "clip.mp4"
            video.write_bytes(b"fake video")

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                Path(command[-1]).write_bytes(b"fake audio")
                return subprocess.CompletedProcess(command, 0, "", "")

            def transcriber(_audio_path, _language, _model, _progress):
                return [
                    SubtitleCue(index=1, start_ms=0, end_ms=1200, text="Hello."),
                    SubtitleCue(index=2, start_ms=1200, end_ms=2400, text="World."),
                ]

            def translator(cues, options):
                self.assertEqual(options.provider, "deepseek")
                self.assertEqual(options.model, "deepseek-v4-flash")
                self.assertEqual(options.base_url, "https://api.deepseek.com")
                return [
                    SubtitleCue(index=cue.index, start_ms=cue.start_ms, end_ms=cue.end_ms, text=f"VI {cue.text}")
                    for cue in cues
                ]

            with patch.dict(os.environ, {}, clear=True):
                with patch("app.env_config._read_windows_environment", return_value=""):
                    result = create_subtitles_from_video(
                        VideoSubtitleOptions(
                            video_path=video,
                            output_dir=root / "exports",
                            project_name="clip",
                            source_language="en",
                            target_language="vi",
                            ai_api_key="test-key",
                            ai_provider="deepseek",
                        ),
                        ffmpeg_path="ffmpeg",
                        runner=runner,
                        transcriber=transcriber,
                        translator=translator,
                    )

            self.assertTrue(result.audio_path.exists())
            self.assertTrue(result.source_srt_path.exists())
            self.assertTrue(result.translated_srt_path and result.translated_srt_path.exists())
            self.assertIn("Hello.", result.source_srt_path.read_text(encoding="utf-8"))
            self.assertIn("VI Hello.", result.translated_srt_path.read_text(encoding="utf-8"))
            self.assertEqual(result.script_text, "VI Hello.\nVI World.")
            self.assertEqual(result.script_language, "vi")
            self.assertIn("subtitle_manifest.json", str(result.manifest_path))
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["ai_provider"], "deepseek")


if __name__ == "__main__":
    unittest.main()
