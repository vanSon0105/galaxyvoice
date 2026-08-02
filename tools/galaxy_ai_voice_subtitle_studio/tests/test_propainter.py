from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.compute import AUTO_DEVICE, CPU_DEVICE, CUDA_DEVICE  # noqa: E402
from app.processes import managed_media_processes  # noqa: E402
from app.propainter import (  # noqa: E402
    ProPainterRuntime,
    build_chunk_extract_command,
    build_chunk_trim_command,
    build_mask_image_command,
    build_propainter_input_command,
    build_propainter_command,
    build_remux_audio_command,
    plan_video_chunks,
    propainter_cuda_available,
    propainter_environment,
    resolve_propainter_device,
    resolve_propainter_runtime,
)


class ProPainterTests(unittest.TestCase):
    def test_runtime_is_discovered_from_the_installed_model_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir) / "ProPainter"
            python = repo / ".venv" / "Scripts" / "python.exe"
            script = repo / "inference_propainter.py"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"python")
            script.write_text("# inference", encoding="utf-8")

            with patch.dict(os.environ, {"GALAXY_PROPAINTER_DIR": str(repo)}, clear=False):
                runtime = resolve_propainter_runtime()

            self.assertEqual(runtime.repo_dir, repo)
            self.assertEqual(runtime.python_executable, python)
            self.assertEqual(runtime.inference_script, script)

    def test_cuda_command_uses_memory_saving_settings_and_fp16(self) -> None:
        runtime = ProPainterRuntime(
            repo_dir=Path("ProPainter"),
            python_executable=Path("python.exe"),
            inference_script=Path("ProPainter/inference_propainter.py"),
        )

        command = build_propainter_command(
            runtime,
            Path("source.mp4"),
            Path("mask.png"),
            Path("work"),
            CUDA_DEVICE,
        )

        self.assertIn("--fp16", command)
        self.assertEqual(command[command.index("--subvideo_length") + 1], "50")
        self.assertEqual(command[command.index("--neighbor_length") + 1], "8")
        self.assertEqual(command[command.index("--ref_stride") + 1], "12")

    def test_cpu_command_does_not_request_fp16(self) -> None:
        runtime = ProPainterRuntime(Path("repo"), Path("python"), Path("inference.py"))
        command = build_propainter_command(
            runtime,
            Path("source.mp4"),
            Path("mask.png"),
            Path("work"),
            CPU_DEVICE,
        )
        self.assertNotIn("--fp16", command)

    def test_cpu_environment_hides_cuda_devices(self) -> None:
        environment = propainter_environment(CPU_DEVICE, {"EXISTING": "1"})
        self.assertEqual(environment["EXISTING"], "1")
        self.assertEqual(environment["CUDA_VISIBLE_DEVICES"], "")

    def test_auto_falls_back_when_propainter_pytorch_cannot_use_cuda(self) -> None:
        runtime = ProPainterRuntime(Path("repo"), Path("python"), Path("inference.py"))
        device = resolve_propainter_device(
            runtime,
            AUTO_DEVICE,
            nvidia_available=True,
            cuda_available=False,
        )
        self.assertEqual(device, CPU_DEVICE)

    def test_explicit_cuda_rejects_an_incompatible_propainter_runtime(self) -> None:
        runtime = ProPainterRuntime(Path("repo"), Path("python"), Path("inference.py"))
        with self.assertRaisesRegex(RuntimeError, "cannot use CUDA"):
            resolve_propainter_device(
                runtime,
                CUDA_DEVICE,
                nvidia_available=True,
                cuda_available=False,
            )

    def test_cuda_probe_requires_cudnn_like_propainter(self) -> None:
        runtime = ProPainterRuntime(Path("repo"), Path("python"), Path("inference.py"))
        completed = subprocess.CompletedProcess([], 0, "1\n", "")
        with patch("app.propainter.subprocess.run", return_value=completed) as run:
            available = propainter_cuda_available(runtime)

        self.assertTrue(available)
        self.assertIn("torch.backends.cudnn.is_available()", run.call_args.args[0][2])

    def test_normalized_input_forces_constant_frame_rate(self) -> None:
        command = build_propainter_input_command(
            "ffmpeg",
            Path("source.mp4"),
            Path("normalized.mp4"),
        )
        self.assertEqual(command[command.index("-fps_mode") + 1], "cfr")

    def test_long_videos_are_split_with_overlap_and_retained_once(self) -> None:
        chunks = plan_video_chunks(45.0, chunk_seconds=20.0, overlap_seconds=1.0)

        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].source_start, 0.0)
        self.assertEqual(chunks[0].source_duration, 21.0)
        self.assertEqual(chunks[1].source_start, 19.0)
        self.assertEqual(chunks[1].source_duration, 22.0)
        self.assertEqual(chunks[2].source_start, 39.0)
        self.assertEqual(sum(chunk.trim_duration for chunk in chunks), 45.0)

        extract = build_chunk_extract_command(
            "ffmpeg", Path("source.mp4"), Path("chunk.mp4"), chunks[1]
        )
        trimmed = build_chunk_trim_command(
            "ffmpeg", Path("inpainted.mp4"), Path("trimmed.mp4"), chunks[1]
        )
        self.assertEqual(extract[extract.index("-ss") + 1], "19.000")
        self.assertIn("trim=start=1.000:duration=20.000", trimmed[trimmed.index("-vf") + 1])

    def test_active_media_process_is_terminated_on_shutdown(self) -> None:
        class FakeProcess:
            pid = 321
            terminated = False

            def poll(self):
                return None

            def terminate(self):
                self.terminated = True

        process = FakeProcess()
        managed_media_processes.reset()
        managed_media_processes.add(process)
        try:
            with patch("app.processes.subprocess.run") as run:
                managed_media_processes.terminate_all()
            if os.name == "nt":
                self.assertEqual(run.call_args.args[0][:2], ["taskkill", "/PID"])
                self.assertIn("/T", run.call_args.args[0])
            else:
                self.assertTrue(process.terminated)
        finally:
            managed_media_processes.discard(process)
            managed_media_processes.reset()

    def test_mask_command_draws_a_white_subtitle_region(self) -> None:
        command = build_mask_image_command(
            "ffmpeg",
            Path("mask.png"),
            video_size=(1920, 1080),
            region=(5, 75, 90, 18),
        )
        video_filter = command[command.index("-vf") + 1]
        self.assertIn("drawbox=x=96:y=810:w=1728:h=194", video_filter)
        self.assertEqual(command[-1], "mask.png")

    def test_remux_command_restores_original_audio(self) -> None:
        command = build_remux_audio_command(
            "ffmpeg",
            Path("inpaint_out.mp4"),
            Path("source.mp4"),
            Path("final.mp4"),
            120.5,
        )
        self.assertIn("1:a?", command)
        self.assertIn("aac", command)
        self.assertNotIn("-shortest", command)
        self.assertEqual(command[command.index("-t") + 1], "120.500")
        self.assertEqual(command[-1], "final.mp4")


if __name__ == "__main__":
    unittest.main()
