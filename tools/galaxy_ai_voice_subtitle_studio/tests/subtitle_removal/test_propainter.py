from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.common.compute import AUTO_DEVICE, CPU_DEVICE, CUDA_DEVICE  # noqa: E402
from app.common.processes import managed_media_processes  # noqa: E402
from app.subtitle_removal.propainter import (  # noqa: E402
    FAST_AI_PROFILE,
    QUALITY_AI_PROFILE,
    ProPainterRuntime,
    ProPainterJobWorker,
    ProPainterSession,
    build_chunk_extract_command,
    build_chunk_trim_command,
    build_dynamic_subtitle_mask_command,
    build_inpainting_input_command,
    build_inpainting_merge_command,
    build_propainter_command,
    generate_dynamic_subtitle_masks,
    install_propainter_runtime,
    plan_inpainting_crop,
    plan_video_chunks,
    propainter_cuda_available,
    propainter_cuda_memory_gb,
    propainter_environment,
    recommended_chunk_seconds,
    recommended_processing_size,
    resolve_propainter_device,
    resolve_propainter_runtime,
    run_propainter,
)


class ProPainterTests(unittest.TestCase):
    def test_installer_is_managed_and_checks_disk_space(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installer = root / "install_propainter.ps1"
            installer.write_text("# installer", encoding="utf-8")
            repository = root / "models" / "ProPainter"
            runtime = ProPainterRuntime(
                repository,
                repository / ".venv" / "Scripts" / "python.exe",
                repository / "inference_propainter.py",
            )
            process = Mock(returncode=0)
            process.poll.return_value = 0
            with (
                patch("app.subtitle_removal.propainter.default_propainter_dir", return_value=repository),
                patch("app.subtitle_removal.propainter.guard_output_space") as guard,
                patch("app.subtitle_removal.propainter.subprocess.Popen", return_value=process) as popen,
                patch("app.subtitle_removal.propainter.resolve_propainter_runtime", return_value=runtime),
                patch.object(managed_media_processes, "add") as add,
                patch.object(managed_media_processes, "discard") as discard,
            ):
                result = install_propainter_runtime(installer, device=CPU_DEVICE, task_id="task-1")

        guard.assert_called_once_with(repository.parent, minimum_mib=8 * 1024)
        self.assertIn("-NoProfile", popen.call_args.args[0])
        add.assert_called_once_with(process, task_id="task-1")
        discard.assert_called_once_with(process)
        self.assertEqual(result["python_path"], str(runtime.python_executable))

    def test_job_worker_reuses_one_process_for_multiple_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = ProPainterRuntime(root, Path("python.exe"), root / "inference_propainter.py")
            session = ProPainterSession(runtime, CPU_DEVICE, CPU_DEVICE, None, FAST_AI_PROFILE)
            progress: list[str] = []

            class FakeStdout:
                def __init__(self) -> None:
                    self.lines = ['GALAXY_JSON:{"event":"ready"}\n']

                def readline(self) -> str:
                    return self.lines.pop(0) if self.lines else ""

            class FakeStdin:
                def __init__(self, owner) -> None:
                    self.owner = owner

                def write(self, raw: str) -> None:
                    payload = json.loads(raw)
                    if payload["command"] == "shutdown":
                        self.owner.returncode = 0
                        return
                    result = Path(payload["output"]) / Path(payload["video"]).stem / "inpaint_out.mp4"
                    result.parent.mkdir(parents=True, exist_ok=True)
                    result.write_bytes(b"video")
                    self.owner.stdout.lines.append(
                        "GALAXY_JSON:"
                        + json.dumps(
                            {
                                "event": "result",
                                "id": payload["id"],
                                "path": str(result),
                                "models_loaded": self.owner.processed == 0,
                            }
                        )
                        + "\n"
                    )
                    self.owner.processed += 1

                def flush(self) -> None:
                    pass

            class FakeProcess:
                def __init__(self) -> None:
                    self.stdout = FakeStdout()
                    self.stdin = FakeStdin(self)
                    self.returncode = None
                    self.processed = 0

                def poll(self):
                    return self.returncode

                def wait(self, timeout=None):
                    self.returncode = 0
                    return 0

            fake_process = FakeProcess()
            with (
                patch("app.subtitle_removal.propainter.subprocess.Popen", return_value=fake_process) as popen,
                patch("app.subtitle_removal.propainter.managed_media_processes.ensure_running"),
                patch("app.subtitle_removal.propainter.managed_media_processes.add"),
                patch("app.subtitle_removal.propainter.managed_media_processes.discard"),
            ):
                with ProPainterJobWorker(session, progress.append) as worker:
                    first = worker.process_chunk(root / "one.mp4", root / "mask.png", root / "out1", "cpu", progress.append)
                    second = worker.process_chunk(root / "two.mp4", root / "mask.png", root / "out2", "cpu", progress.append)

            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
            self.assertEqual(fake_process.processed, 2)
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(sum("models loaded once" in line for line in progress), 1)

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

    def test_cuda_command_adapts_quality_settings_to_12gb_and_uses_fp16(self) -> None:
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
            gpu_memory_gb=12.0,
            profile=QUALITY_AI_PROFILE,
        )

        self.assertIn("--fp16", command)
        self.assertEqual(command[command.index("--subvideo_length") + 1], "24")
        self.assertEqual(command[command.index("--neighbor_length") + 1], "8")
        self.assertEqual(command[command.index("--ref_stride") + 1], "12")

    def test_fast_ai_uses_lighter_temporal_settings_on_12gb_cuda(self) -> None:
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
            gpu_memory_gb=12.0,
            profile=FAST_AI_PROFILE,
        )

        self.assertIn("--fp16", command)
        self.assertEqual(command[command.index("--subvideo_length") + 1], "40")
        self.assertEqual(command[command.index("--neighbor_length") + 1], "6")
        self.assertEqual(command[command.index("--ref_stride") + 1], "15")

    def test_6gb_cuda_uses_smaller_quality_batches_and_context(self) -> None:
        runtime = ProPainterRuntime(Path("repo"), Path("python"), Path("inference.py"))

        command = build_propainter_command(
            runtime,
            Path("source.mp4"),
            Path("mask.png"),
            Path("work"),
            CUDA_DEVICE,
            gpu_memory_gb=6.0,
            profile=QUALITY_AI_PROFILE,
        )

        self.assertEqual(command[command.index("--subvideo_length") + 1], "16")
        self.assertEqual(command[command.index("--neighbor_length") + 1], "6")
        self.assertEqual(command[command.index("--ref_stride") + 1], "8")
        self.assertIn("--fp16", command)

    def test_6gb_cuda_uses_conservative_fast_ai_batches(self) -> None:
        runtime = ProPainterRuntime(Path("repo"), Path("python"), Path("inference.py"))

        command = build_propainter_command(
            runtime,
            Path("source.mp4"),
            Path("mask.png"),
            Path("work"),
            CUDA_DEVICE,
            gpu_memory_gb=6.0,
            profile=FAST_AI_PROFILE,
        )

        self.assertEqual(command[command.index("--subvideo_length") + 1], "24")
        self.assertEqual(command[command.index("--ref_stride") + 1], "12")

    def test_6gb_cuda_reduces_outer_chunks_and_processing_resolution(self) -> None:
        runtime = ProPainterRuntime(Path("repo"), Path("python"), Path("inference.py"))
        fast_session = ProPainterSession(
            runtime, CUDA_DEVICE, CUDA_DEVICE, 6.0, FAST_AI_PROFILE
        )
        quality_session = ProPainterSession(
            runtime, CUDA_DEVICE, CUDA_DEVICE, 6.0, QUALITY_AI_PROFILE
        )

        self.assertEqual(recommended_chunk_seconds(fast_session), 15.0)
        self.assertEqual(recommended_chunk_seconds(quality_session), 12.0)
        self.assertEqual(recommended_processing_size(fast_session), (480, 240))
        self.assertEqual(recommended_processing_size(quality_session), (640, 360))
        plan = plan_inpainting_crop(
            video_size=(1920, 1080),
            region=(5, 75, 90, 20),
            profile=FAST_AI_PROFILE,
            maximum_processing_size=recommended_processing_size(fast_session),
        )
        self.assertLessEqual(plan.processing_width, 480)
        self.assertLessEqual(plan.processing_height, 240)

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
        with patch("app.subtitle_removal.propainter.subprocess.run", return_value=completed) as run:
            available = propainter_cuda_available(runtime)

        self.assertTrue(available)
        self.assertIn("torch.backends.cudnn.is_available()", run.call_args.args[0][2])

    def test_cuda_memory_probe_uses_currently_free_memory(self) -> None:
        runtime = ProPainterRuntime(Path("repo"), Path("python"), Path("inference.py"))
        completed = subprocess.CompletedProcess([], 0, "5.5\n", "")
        with patch("app.subtitle_removal.propainter.subprocess.run", return_value=completed) as run:
            memory = propainter_cuda_memory_gb(runtime)

        self.assertEqual(memory, 5.5)
        self.assertIn("torch.cuda.mem_get_info()", run.call_args.args[0][2])

    def test_cuda_oom_retries_once_with_the_lowest_memory_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "source.mp4"
            mask = root / "mask.png"
            output_root = root / "output"
            video.write_bytes(b"video")
            mask.write_bytes(b"mask")
            runtime = ProPainterRuntime(root, Path("python"), Path("inference.py"))
            session = ProPainterSession(runtime, CUDA_DEVICE, CUDA_DEVICE, 6.0, QUALITY_AI_PROFILE)

            class FakeProcess:
                def __init__(self, return_code: int, lines: list[str], create_result: bool = False):
                    self.return_code = return_code
                    self.stdout = lines
                    self.create_result = create_result

                def wait(self):
                    if self.create_result:
                        result = output_root / video.stem / "inpaint_out.mp4"
                        result.parent.mkdir(parents=True, exist_ok=True)
                        result.write_bytes(b"result")
                    return self.return_code

            processes = [
                FakeProcess(1, ["torch.OutOfMemoryError: CUDA out of memory\n"]),
                FakeProcess(0, [], create_result=True),
            ]
            with (
                patch("app.subtitle_removal.propainter.subprocess.Popen", side_effect=processes) as popen,
                patch("app.subtitle_removal.propainter.managed_media_processes.ensure_running"),
                patch("app.subtitle_removal.propainter.managed_media_processes.add"),
                patch("app.subtitle_removal.propainter.managed_media_processes.discard"),
            ):
                result = run_propainter(
                    video,
                    mask,
                    output_root,
                    CUDA_DEVICE,
                    lambda _message: None,
                    session=session,
                )

            self.assertTrue(result.is_file())
            self.assertEqual(popen.call_count, 2)
            first_command = popen.call_args_list[0].args[0]
            retry_command = popen.call_args_list[1].args[0]
            self.assertEqual(first_command[first_command.index("--subvideo_length") + 1], "16")
            self.assertEqual(retry_command[retry_command.index("--subvideo_length") + 1], "16")
            self.assertEqual(retry_command[retry_command.index("--resize_ratio") + 1], "0.75")
            self.assertEqual(session.gpu_memory_gb, 0.0)

    def test_fast_ai_crops_and_downscales_only_the_subtitle_band(self) -> None:
        plan = plan_inpainting_crop(
            video_size=(1280, 720),
            region=(5, 75, 90, 20),
            profile=FAST_AI_PROFILE,
        )

        self.assertLessEqual(plan.processing_width, 640)
        self.assertLessEqual(plan.processing_height, 320)
        self.assertLess(plan.crop_height, 720)
        self.assertGreater(plan.crop_y, 0)

        command = build_inpainting_input_command(
            "ffmpeg",
            Path("source.mp4"),
            Path("processing.mp4"),
            plan,
        )
        video_filter = command[command.index("-vf") + 1]
        self.assertIn(
            f"crop={plan.crop_width}:{plan.crop_height}:{plan.crop_x}:{plan.crop_y}",
            video_filter,
        )
        self.assertIn(
            f"scale={plan.processing_width}:{plan.processing_height}",
            video_filter,
        )
        self.assertEqual(command[command.index("-fps_mode") + 1], "cfr")

    def test_fast_ai_keeps_raft_pyramid_large_enough_for_thin_region(self) -> None:
        plan = plan_inpainting_crop(
            video_size=(1280, 720),
            region=(5, 80, 90, 9),
            profile=FAST_AI_PROFILE,
        )

        self.assertEqual(
            (plan.processing_width, plan.processing_height),
            (640, 128),
        )

    def test_dynamic_mask_command_uses_propainter_python_and_processing_roi(self) -> None:
        runtime = ProPainterRuntime(Path("repo"), Path("venv-python"), Path("inference.py"))
        plan = plan_inpainting_crop(
            video_size=(1280, 720),
            region=(10, 80, 79, 12),
            profile=FAST_AI_PROFILE,
        )

        command = build_dynamic_subtitle_mask_command(
            runtime,
            Path("processing.mp4"),
            Path("masks"),
            plan,
        )

        self.assertEqual(command[0], "venv-python")
        self.assertTrue(command[1].endswith("propainter_mask_worker.py"))
        self.assertEqual(command[command.index("--video") + 1], "processing.mp4")
        self.assertEqual(command[command.index("--output") + 1], "masks")
        self.assertEqual(
            command[command.index("--roi") + 1 :],
            [
                str(plan.mask_x),
                str(plan.mask_y),
                str(plan.mask_width),
                str(plan.mask_height),
            ],
        )

    def test_dynamic_mask_worker_is_terminated_when_progress_callback_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = ProPainterRuntime(root, Path("venv-python"), Path("inference.py"))
            plan = plan_inpainting_crop(
                video_size=(1280, 720),
                region=(10, 80, 79, 12),
                profile=FAST_AI_PROFILE,
            )

            class FakeProcess:
                stdout = ["Detecting subtitle glyphs...\n"]
                terminated = False

                def poll(self):
                    return None

                def terminate(self):
                    self.terminated = True

                def wait(self, timeout=None):
                    return -15 if self.terminated else 0

            process = FakeProcess()

            def failing_progress(_message: str) -> None:
                raise RuntimeError("progress callback failed")

            with (
                patch("app.subtitle_removal.propainter.subprocess.Popen", return_value=process),
                patch("app.subtitle_removal.propainter.managed_media_processes.ensure_running"),
                patch("app.subtitle_removal.propainter.managed_media_processes.add"),
                patch("app.subtitle_removal.propainter.managed_media_processes.discard") as discard,
                self.assertRaisesRegex(RuntimeError, "progress callback failed"),
            ):
                generate_dynamic_subtitle_masks(
                    runtime,
                    root / "input.mp4",
                    root / "masks",
                    plan,
                    failing_progress,
                )

            self.assertTrue(process.terminated)
            discard.assert_called_once_with(process)

    def test_ai_merge_replaces_only_selected_region_in_original_video(self) -> None:
        plan = plan_inpainting_crop(
            video_size=(1280, 720),
            region=(5, 75, 90, 20),
            profile=QUALITY_AI_PROFILE,
        )

        command = build_inpainting_merge_command(
            "ffmpeg",
            Path("source.mp4"),
            Path("inpainted_crop.mp4"),
            Path("final.mp4"),
            plan,
            duration_seconds=12.5,
        )

        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn(
            f"scale={plan.crop_width}:{plan.crop_height}",
            filter_graph,
        )
        self.assertIn(
            f"crop={plan.region_width}:{plan.region_height}:"
            f"{plan.region_x - plan.crop_x}:{plan.region_y - plan.crop_y}:exact=1",
            filter_graph,
        )
        self.assertIn(f"overlay=x={plan.region_x}:y={plan.region_y}", filter_graph)
        self.assertEqual(filter_graph.count("setpts=PTS-STARTPTS"), 2)
        self.assertIn("alphamerge=shortest=1", filter_graph)
        self.assertIn("boxblur=luma_radius=4", filter_graph)
        self.assertIn("eof_action=repeat", filter_graph)
        self.assertNotIn(
            f"overlay=x={plan.region_x}:y={plan.region_y}:shortest=1",
            filter_graph,
        )
        self.assertIn("0:a?", command)
        self.assertEqual(
            command[command.index("-af") + 1],
            "aresample=async=1:first_pts=0",
        )

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
            with patch("app.common.processes.subprocess.run") as run:
                managed_media_processes.terminate_all()
            if os.name == "nt":
                self.assertEqual(run.call_args.args[0][:2], ["taskkill", "/PID"])
                self.assertIn("/T", run.call_args.args[0])
            else:
                self.assertTrue(process.terminated)
        finally:
            managed_media_processes.discard(process)
            managed_media_processes.reset()

if __name__ == "__main__":
    unittest.main()
