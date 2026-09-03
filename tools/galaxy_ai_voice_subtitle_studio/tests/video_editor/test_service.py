from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from app.video_editor.service import (
    CPU_ENCODER,
    INTEL_ENCODER,
    NVIDIA_ENCODER,
    EditorExportOptions,
    EditorMediaClip,
    EditorMediaInfo,
    EditorVideoSegment,
    build_editor_export_command,
    build_editor_frame_command,
    export_editor_video,
    probe_audio_duration,
    probe_editor_media,
    resolve_editor_encoder,
)


class EditorServiceTests(unittest.TestCase):
    def test_probe_video_reads_rotation_duration_and_audio(self) -> None:
        payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                    "tags": {"rotate": "90"},
                },
                {"codec_type": "audio"},
            ],
            "format": {"duration": "12.5"},
        }
        runner = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # noqa: E731
            [], 0, stdout=json.dumps(payload), stderr=""
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "clip.mp4"
            path.touch()
            result = probe_editor_media(path, ffprobe_path="ffprobe", runner=runner)

        self.assertEqual((result.width, result.height), (1080, 1920))
        self.assertAlmostEqual(result.fps, 29.97, places=2)
        self.assertTrue(result.has_audio)

    def test_probe_audio_duration_validates_ffprobe_output(self) -> None:
        runner = lambda *_args, **_kwargs: subprocess.CompletedProcess(  # noqa: E731
            [], 0, stdout="8.250\n", stderr=""
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "voice.wav"
            path.touch()
            self.assertEqual(probe_audio_duration(path, "ffprobe", runner), 8.25)

    def test_auto_encoder_prefers_nvidia_then_intel_then_cpu(self) -> None:
        all_encoders = {"libx264", "h264_nvenc", "h264_qsv"}
        self.assertEqual(resolve_editor_encoder("auto", all_encoders, nvidia_available=True), NVIDIA_ENCODER)
        self.assertIn(
            resolve_editor_encoder("auto", all_encoders, nvidia_available=False),
            {INTEL_ENCODER, CPU_ENCODER},
        )
        self.assertEqual(
            resolve_editor_encoder("auto", {"libx264"}, nvidia_available=False),
            CPU_ENCODER,
        )

    def test_export_command_supports_2k_60fps_subtitles_and_mixed_audio(self) -> None:
        options = EditorExportOptions(
            video_path=Path("source.mp4"),
            audio_path=Path("voice.wav"),
            output_dir=Path("exports"),
            resolution="2k",
            fps="60",
            encoder="cpu",
            audio_offset_ms=500,
        )
        media = EditorMediaInfo(20.0, 1920, 1080, 24.0, True)

        command = build_editor_export_command(
            "ffmpeg",
            options,
            media,
            Path("result.mp4"),
            encoder=CPU_ENCODER,
            subtitle_path="result.srt",
        )

        video_filter = command[command.index("-vf") + 1]
        audio_filter = command[command.index("-filter_complex") + 1]
        self.assertIn("scale=2560:1440", video_filter)
        self.assertIn("fps=60", video_filter)
        self.assertIn("subtitles=", video_filter)
        self.assertIn("adelay=500", audio_filter)
        self.assertIn("amix=inputs=2", audio_filter)
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")

    def test_export_command_trims_and_concatenates_video_segments(self) -> None:
        options = EditorExportOptions(
            video_path=Path("source.mp4"),
            output_dir=Path("exports"),
            video_segments=(
                EditorVideoSegment(1_000, 4_000),
                EditorVideoSegment(8_500, 10_000),
            ),
        )
        media = EditorMediaInfo(20.0, 1920, 1080, 24.0, True)

        command = build_editor_export_command(
            "ffmpeg", options, media, Path("result.mp4"),
            encoder=CPU_ENCODER, subtitle_path=None,
        )

        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("trim=start=1.000:end=4.000", graph)
        self.assertIn("trim=start=8.500:end=10.000", graph)
        self.assertIn("concat=n=2:v=1:a=0", graph)
        self.assertIn("atrim=start=1.000:end=4.000", graph)
        self.assertIn("concat=n=2:v=0:a=1", graph)
        self.assertEqual(command[command.index("-t") + 1], "4.500")
        self.assertIn("[editor_video]", command)
        self.assertIn("[editor_audio]", command)

    def test_export_command_composites_positioned_video_and_audio_clips(self) -> None:
        options = EditorExportOptions(
            video_path=Path("base.mp4"),
            output_dir=Path("exports"),
            video_clips=(
                EditorMediaClip(Path("base.mp4"), 0, 0, 8_000, 1, 100, True),
                EditorMediaClip(Path("overlay.mp4"), 2_000, 500, 3_500, 0, 100, False),
            ),
            audio_clips=(
                EditorMediaClip(Path("voice-one.wav"), 1_000, 0, 2_000, 2, 80, True),
                EditorMediaClip(Path("voice-two.wav"), 4_000, 250, 2_250, 3, 90, True),
            ),
        )
        media = EditorMediaInfo(8.0, 1920, 1080, 30.0, True)

        command = build_editor_export_command(
            "ffmpeg", options, media, Path("result.mp4"), encoder=CPU_ENCODER, subtitle_path=None,
        )

        graph = command[command.index("-filter_complex") + 1]
        self.assertEqual(command.count("-i"), 4)
        self.assertIn("overlay=eof_action=pass", graph)
        self.assertIn("trim=start=0.500:end=3.500", graph)
        self.assertIn("adelay=1000:all=1", graph)
        self.assertIn("adelay=4000:all=1", graph)
        self.assertIn("amix=inputs=3", graph)
        self.assertEqual(command[command.index("-t") + 1], "8.000")

    def test_export_command_rejects_segment_outside_source(self) -> None:
        options = EditorExportOptions(
            video_path=Path("source.mp4"),
            output_dir=Path("exports"),
            video_segments=(EditorVideoSegment(5_000, 21_000),),
        )
        media = EditorMediaInfo(20.0, 1920, 1080, 24.0, True)

        with self.assertRaisesRegex(ValueError, "segment"):
            build_editor_export_command(
                "ffmpeg", options, media, Path("result.mp4"),
                encoder=CPU_ENCODER, subtitle_path=None,
            )

    def test_export_command_covers_all_resolutions_fps_encoders_and_replace_audio(self) -> None:
        media = EditorMediaInfo(20.0, 1921, 1081, 23.976, True)
        codec_by_encoder = {
            CPU_ENCODER: "libx264",
            NVIDIA_ENCODER: "h264_nvenc",
            INTEL_ENCODER: "h264_qsv",
        }
        for resolution in ("original", "720p", "1080p", "2k"):
            for fps in ("source", "24", "30", "50", "60"):
                for encoder, codec in codec_by_encoder.items():
                    with self.subTest(resolution=resolution, fps=fps, encoder=encoder):
                        options = EditorExportOptions(
                            video_path=Path("source.mp4"),
                            audio_path=Path("voice.wav"),
                            output_dir=Path("exports"),
                            resolution=resolution,
                            fps=fps,
                            encoder=encoder,
                            audio_mode="replace",
                        )
                        command = build_editor_export_command(
                            "ffmpeg", options, media, Path("result.mp4"),
                            encoder=encoder, subtitle_path=None,
                        )
                        graph = command[command.index("-filter_complex") + 1]
                        self.assertNotIn("amix=", graph)
                        self.assertEqual(command[command.index("-c:v") + 1], codec)
                        if fps == "source":
                            self.assertNotIn("fps=", " ".join(command))
                        else:
                            self.assertIn(f"fps={fps}", command[command.index("-vf") + 1])

    def test_still_preview_outputs_exactly_one_raw_frame(self) -> None:
        command = build_editor_frame_command(
            "ffmpeg",
            Path("clip.mp4"),
            position_seconds=4.5,
            width=384,
            height=216,
        )

        self.assertNotIn("-re", command)
        self.assertEqual(command[command.index("-frames:v") + 1], "1")
        self.assertEqual(command[command.index("-ss") + 1], "4.500")
        self.assertEqual(command[-1], "pipe:1")

    def test_cancelled_hardware_export_does_not_retry_on_cpu(self) -> None:
        cancellation = Event()
        cancellation.set()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            source.touch()
            options = EditorExportOptions(
                video_path=source,
                output_dir=root / "exports",
                encoder="auto",
            )
            with (
                patch(
                    "app.video_editor.service.probe_editor_media",
                    return_value=EditorMediaInfo(2.0, 640, 360, 24.0, False),
                ),
                patch(
                    "app.video_editor.service.available_h264_encoders",
                    return_value={"libx264", "h264_nvenc"},
                ),
                patch(
                    "app.video_editor.service.resolve_editor_encoder",
                    return_value=NVIDIA_ENCODER,
                ),
                patch(
                    "app.video_editor.service._run_export",
                    side_effect=RuntimeError("Video export was stopped."),
                ) as run_export,
            ):
                with self.assertRaisesRegex(RuntimeError, "stopped"):
                    export_editor_video(
                        options,
                        cancellation=cancellation,
                        ffmpeg_path="ffmpeg",
                    )

            run_export.assert_called_once()

    def test_export_rejects_audio_offset_after_video_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            audio = root / "voice.wav"
            source.touch()
            audio.touch()
            options = EditorExportOptions(
                video_path=source,
                audio_path=audio,
                output_dir=root / "exports",
                audio_offset_ms=2_000,
            )
            with patch(
                "app.video_editor.service.probe_editor_media",
                return_value=EditorMediaInfo(2.0, 640, 360, 24.0, False),
            ):
                with self.assertRaisesRegex(ValueError, "trước khi video kết thúc"):
                    export_editor_video(options, ffmpeg_path="ffmpeg")

            self.assertFalse((root / "exports").exists())


if __name__ == "__main__":
    unittest.main()
