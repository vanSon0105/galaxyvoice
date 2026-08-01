from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.subtitle_removal import (  # noqa: E402
    BLUR_MODE,
    FILL_MODE,
    STRIP_MODE,
    SubtitleRemovalOptions,
    build_blur_subtitles_command,
    build_fill_subtitles_command,
    build_preview_command,
    build_strip_subtitles_command,
    probe_video_size,
    remove_subtitles_from_video,
)


class SubtitleRemovalTests(unittest.TestCase):
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
        command = build_preview_command("ffmpeg", Path("source.mp4"), Path("preview.png"))

        self.assertIn("scale=480:270", command)
        self.assertEqual(command[command.index("-ss") + 1], "0")
        self.assertEqual(command[-1], "preview.png")

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
