from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ffmpeg import find_ffmpeg, find_ffprobe  # noqa: E402
from app.subtitle_removal import (  # noqa: E402
    AI_INPAINT_MODE,
    BLUR_MODE,
    FILL_MODE,
    STRIP_MODE,
    SubtitleRemovalOptions,
    build_audio_playback_command,
    build_blur_subtitles_command,
    build_fill_subtitles_command,
    build_playback_command,
    build_preview_command,
    build_strip_subtitles_command,
    probe_video_size,
    probe_video_duration,
    remove_subtitles_from_video,
)


class SubtitleRemovalTests(unittest.TestCase):
    def test_ai_inpainting_creates_mask_restores_audio_and_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            commands: list[list[str]] = []
            ai_calls: list[tuple[Path, Path, Path, str]] = []

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                Path(command[-1]).write_bytes(b"generated")
                return subprocess.CompletedProcess(command, 0, "", "")

            def probe_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                if "format=duration" in command:
                    return subprocess.CompletedProcess(command, 0, "12.0\n", "")
                return subprocess.CompletedProcess(
                    command,
                    0,
                    '{"streams": [{"width": 1280, "height": 720}]}',
                    "",
                )

            def ai_inpainter(video, mask, output_root, device, _progress):
                ai_calls.append((video, mask, output_root, device))
                generated = output_root / video.stem / "inpaint_out.mp4"
                generated.parent.mkdir(parents=True)
                generated.write_bytes(b"ai video")
                return generated

            result = remove_subtitles_from_video(
                SubtitleRemovalOptions(
                    video_path=source,
                    output_dir=root / "exports",
                    project_name="AI Clean",
                    mode=AI_INPAINT_MODE,
                    processing_device="cpu",
                ),
                ffmpeg_path="ffmpeg",
                ffprobe_path="ffprobe",
                runner=runner,
                probe_runner=probe_runner,
                ai_inpainter=ai_inpainter,
            )

            self.assertEqual(len(ai_calls), 1)
            self.assertEqual(ai_calls[0][3], "cpu")
            self.assertEqual(len(commands), 3)
            self.assertIn("drawbox=", commands[0][commands[0].index("-vf") + 1])
            self.assertIn("libx264", commands[1])
            self.assertIn("1:a?", commands[2])
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["mode"], AI_INPAINT_MODE)
            self.assertEqual(manifest["processing_device"], "cpu")
            self.assertTrue(any("non-commercial" in warning.lower() for warning in result.warnings))

    def test_long_ai_inpainting_processes_memory_safe_overlapping_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            commands: list[list[str]] = []
            ai_inputs: list[Path] = []

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                Path(command[-1]).write_bytes(b"generated")
                return subprocess.CompletedProcess(command, 0, "", "")

            def probe_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                if "format=duration" in command:
                    return subprocess.CompletedProcess(command, 0, "45.0\n", "")
                return subprocess.CompletedProcess(
                    command,
                    0,
                    '{"streams": [{"width": 1280, "height": 720}]}',
                    "",
                )

            def ai_inpainter(video, _mask, output_root, _device, _progress):
                ai_inputs.append(video)
                generated = output_root / video.stem / "inpaint_out.mp4"
                generated.parent.mkdir(parents=True)
                generated.write_bytes(b"ai video")
                return generated

            result = remove_subtitles_from_video(
                SubtitleRemovalOptions(
                    video_path=source,
                    output_dir=root / "exports",
                    mode=AI_INPAINT_MODE,
                    processing_device="cpu",
                ),
                ffmpeg_path="ffmpeg",
                ffprobe_path="ffprobe",
                runner=runner,
                probe_runner=probe_runner,
                ai_inpainter=ai_inpainter,
            )

            self.assertEqual([path.name for path in ai_inputs], [
                "chunk_0001.mp4",
                "chunk_0002.mp4",
                "chunk_0003.mp4",
            ])
            concat_commands = [command for command in commands if "concat" in command]
            self.assertEqual(len(concat_commands), 1)
            self.assertTrue(result.video_path.is_file())
            self.assertFalse((result.project_dir / "_propainter").exists())

    def test_real_ffmpeg_ai_pipeline_preserves_video_and_audio(self) -> None:
        ffmpeg = find_ffmpeg()
        ffprobe = find_ffprobe()
        if not ffmpeg or not ffprobe:
            self.skipTest("Bundled FFmpeg is unavailable.")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=160x90:rate=12:duration=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=44100:duration=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    str(source),
                ],
                check=True,
            )

            def ai_inpainter(video, _mask, output_root, _device, _progress):
                generated = output_root / video.stem / "inpaint_out.mp4"
                generated.parent.mkdir(parents=True)
                shutil.copy2(video, generated)
                return generated

            result = remove_subtitles_from_video(
                SubtitleRemovalOptions(
                    video_path=source,
                    output_dir=root / "exports",
                    mode=AI_INPAINT_MODE,
                    processing_device="cpu",
                ),
                ffmpeg_path=ffmpeg,
                ffprobe_path=ffprobe,
                ai_inpainter=ai_inpainter,
            )
            completed = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type:format=duration",
                    "-of",
                    "json",
                    str(result.video_path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(completed.stdout)
            stream_types = {stream["codec_type"] for stream in payload["streams"]}
            self.assertEqual(stream_types, {"video", "audio"})
            self.assertAlmostEqual(float(payload["format"]["duration"]), 2.0, delta=0.2)

    def test_strip_command_removes_subtitle_streams_without_reencoding(self) -> None:
        command = build_strip_subtitles_command(
            "ffmpeg",
            Path("source.mkv"),
            Path("clean.mkv"),
        )

        self.assertIn("-0:s", command)
        self.assertIn("copy", command)
        self.assertNotIn("libx264", command)
        self.assertEqual(command[-1], "clean.mkv")

    def test_blur_command_uses_selected_region_and_strength(self) -> None:
        command = build_blur_subtitles_command(
            "ffmpeg",
            Path("source.mp4"),
            Path("clean.mp4"),
            region=(5, 74, 90, 20),
            blur_strength=24,
        )

        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("crop=w=iw*0.900000:h=ih*0.200000", filter_graph)
        self.assertIn("x=iw*0.050000:y=ih*0.740000", filter_graph)
        self.assertIn(r"boxblur=luma_radius=min(24\,min(w\,h)/2-1)", filter_graph)
        self.assertIn(r"chroma_radius=min(24\,min(cw\,ch)/2-1)", filter_graph)
        self.assertIn("overlay=x=main_w*0.050000:y=main_h*0.740000", filter_graph)
        self.assertIn("libx264", command)
        self.assertIn("copy", command)

    def test_fill_command_uses_delogo_for_the_selected_region(self) -> None:
        command = build_fill_subtitles_command(
            "ffmpeg",
            Path("source.mp4"),
            Path("clean.mp4"),
            region=(8, 70, 84, 22),
            video_size=(1920, 1080),
        )

        video_filter = command[command.index("-vf") + 1]
        self.assertIn("delogo=", video_filter)
        self.assertIn("x=154", video_filter)
        self.assertIn("y=756", video_filter)
        self.assertIn("w=1612", video_filter)
        self.assertIn("h=238", video_filter)

    def test_fill_command_keeps_delogo_inside_the_frame_edges(self) -> None:
        command = build_fill_subtitles_command(
            "ffmpeg",
            Path("source.mp4"),
            Path("clean.mp4"),
            region=(0, 80, 100, 20),
            video_size=(640, 360),
        )

        video_filter = command[command.index("-vf") + 1]
        self.assertIn("x=1", video_filter)
        self.assertIn("y=288", video_filter)
        self.assertIn("w=638", video_filter)
        self.assertIn("h=71", video_filter)

    def test_probe_video_size_reads_the_first_video_stream(self) -> None:
        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                0,
                '{"streams": [{"width": 1920, "height": 1080}]}',
                "",
            )

        size = probe_video_size(Path("source.mp4"), ffprobe_path="ffprobe", runner=runner)

        self.assertEqual(size, (1920, 1080))

    def test_probe_video_size_swaps_dimensions_for_rotated_video(self) -> None:
        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                0,
                '{"streams": [{"width": 1920, "height": 1080, "side_data_list": [{"rotation": -90}]}]}',
                "",
            )

        size = probe_video_size(Path("portrait.mp4"), ffprobe_path="ffprobe", runner=runner)

        self.assertEqual(size, (1080, 1920))

    def test_probe_video_size_supports_legacy_rotate_tag(self) -> None:
        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                0,
                '{"streams": [{"width": 1280, "height": 720, "tags": {"rotate": "270"}}]}',
                "",
            )

        size = probe_video_size(Path("portrait.mov"), ffprobe_path="ffprobe", runner=runner)

        self.assertEqual(size, (720, 1280))

    def test_preview_command_creates_a_stable_canvas(self) -> None:
        command = build_preview_command(
            "ffmpeg",
            Path("source.mp4"),
            Path("preview.png"),
            timestamp_seconds=12.5,
        )

        self.assertIn("scale=480:270", command)
        self.assertEqual(command[command.index("-ss") + 1], "12.500")
        self.assertEqual(command[-1], "preview.png")

    def test_playback_command_streams_realtime_rgb_frames(self) -> None:
        command = build_playback_command(
            "ffmpeg",
            Path("source.mp4"),
            start_seconds=8.25,
            width=480,
            height=270,
            fps=12,
        )

        self.assertEqual(command[command.index("-ss") + 1], "8.250")
        self.assertIn("-re", command)
        self.assertIn("scale=480:270,fps=12", command)
        self.assertEqual(command[-3:], ["-pix_fmt", "rgb24", "pipe:1"])

    def test_audio_playback_command_uses_ffplay_without_a_window(self) -> None:
        command = build_audio_playback_command("ffplay", Path("source.mp4"), start_seconds=8.25)

        self.assertIn("-nodisp", command)
        self.assertIn("-autoexit", command)
        self.assertEqual(command[command.index("-ss") + 1], "8.250")
        self.assertEqual(command[-1], "source.mp4")

    def test_probe_video_duration_reads_format_duration(self) -> None:
        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, "83.625\n", "")

        duration = probe_video_duration(Path("source.mp4"), ffprobe_path="ffprobe", runner=runner)

        self.assertEqual(duration, 83.625)

    def test_processing_creates_video_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            commands: list[list[str]] = []

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                Path(command[-1]).write_bytes(b"clean video")
                return subprocess.CompletedProcess(command, 0, "", "")

            result = remove_subtitles_from_video(
                SubtitleRemovalOptions(
                    video_path=source,
                    output_dir=root / "exports",
                    project_name="Clean Clip",
                    mode=BLUR_MODE,
                    region_x=5,
                    region_y=75,
                    region_width=90,
                    region_height=18,
                    blur_strength=16,
                ),
                ffmpeg_path="ffmpeg",
                runner=runner,
            )

            self.assertEqual(len(commands), 1)
            self.assertTrue(result.video_path.exists())
            self.assertTrue(result.manifest_path.exists())
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["mode"], BLUR_MODE)
            self.assertEqual(manifest["region"], {"x": 5, "y": 75, "width": 90, "height": 18})

    def test_region_must_fit_inside_the_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            source.write_bytes(b"video")

            with self.assertRaisesRegex(ValueError, "inside the video"):
                remove_subtitles_from_video(
                    SubtitleRemovalOptions(
                        video_path=source,
                        output_dir=root / "exports",
                        mode=FILL_MODE,
                        region_x=80,
                        region_y=75,
                        region_width=30,
                        region_height=20,
                    ),
                    ffmpeg_path="ffmpeg",
                )

    def test_failed_processing_removes_partial_project_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            source.write_bytes(b"video")

            def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
                Path(command[-1]).write_bytes(b"partial")
                return subprocess.CompletedProcess(command, 1, "", "encoding failed")

            with self.assertRaisesRegex(RuntimeError, "encoding failed"):
                remove_subtitles_from_video(
                    SubtitleRemovalOptions(
                        video_path=source,
                        output_dir=root / "exports",
                        project_name="clip",
                        mode=BLUR_MODE,
                    ),
                    ffmpeg_path="ffmpeg",
                    runner=runner,
                )

            self.assertEqual(list((root / "exports").iterdir()), [])

    def test_unknown_mode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            source.write_bytes(b"video")

            with self.assertRaisesRegex(ValueError, "Unknown subtitle removal mode"):
                remove_subtitles_from_video(
                    SubtitleRemovalOptions(
                        video_path=source,
                        output_dir=root / "exports",
                        mode="unknown",
                    ),
                    ffmpeg_path="ffmpeg",
                )

        self.assertIn(STRIP_MODE, {STRIP_MODE, BLUR_MODE, FILL_MODE})


if __name__ == "__main__":
    unittest.main()
