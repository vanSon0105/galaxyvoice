from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.audio_separation.service import (  # noqa: E402
    CPU_AUDIO_DEVICE,
    CUDA_AUDIO_DEVICE,
    DEMUCS_METHOD,
    DIRECTML_AUDIO_DEVICE,
    MDXC_METHOD,
    MDX_METHOD,
    VR_METHOD,
    AudioSeparationOptions,
    AudioSeparatorRuntime,
    DownloadableAudioModel,
    UVRModel,
    audio_model_download_dir,
    audio_separator_runtime_ready,
    build_audio_separator_command,
    build_prepare_audio_command,
    download_audio_model,
    discover_uvr_models,
    load_audio_presets,
    resolve_audio_device,
    save_audio_presets,
    separate_audio,
    serialize_downloadable_audio_models,
    _run_streaming_command,
)


class AudioSeparationTests(unittest.TestCase):
    def test_discovers_models_from_the_local_uvr_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mdx = root / "models" / "MDX_Net_Models"
            vr = root / "models" / "VR_Models"
            demucs = root / "models" / "Demucs_Models" / "v3_v4_repo"
            mdx.mkdir(parents=True)
            vr.mkdir(parents=True)
            demucs.mkdir(parents=True)
            (mdx / "Kim_Vocal_2.onnx").write_bytes(b"model")
            (vr / "1_HP-UVR.pth").write_bytes(b"model")
            (demucs / "htdemucs.yaml").write_text("name: htdemucs", encoding="utf-8")
            (demucs / "955717e8-8726e21a.th").write_bytes(b"weights")

            models = discover_uvr_models(root)

        self.assertEqual(
            [(model.method, model.filename) for model in models],
            [
                (MDX_METHOD, "Kim_Vocal_2.onnx"),
                (VR_METHOD, "1_HP-UVR.pth"),
                (DEMUCS_METHOD, "htdemucs.yaml"),
            ],
        )
        self.assertEqual(models[0].label, "Kim Vocal 2")

    def test_discovers_mdxc_models_from_the_local_model_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mdxc = root / "models" / "MDX_Net_Models"
            mdxc.mkdir(parents=True)
            (mdxc / "melband_roformer.ckpt").write_bytes(b"model")

            models = discover_uvr_models(root)

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].method, MDXC_METHOD)

    def test_catalog_marks_downloaded_models_and_maps_engine_types(self) -> None:
        catalog = (
            DownloadableAudioModel(
                filename="Kim_Vocal_2.onnx",
                name="Kim Vocal 2",
                model_type="MDX",
                method=MDX_METHOD,
                stems=("vocals", "instrumental"),
            ),
            DownloadableAudioModel(
                filename="melband_roformer.ckpt",
                name="MelBand RoFormer",
                model_type="MDXC",
                method=MDXC_METHOD,
                stems=("vocals", "instrumental"),
            ),
        )
        installed = (
            UVRModel(MDX_METHOD, "Kim Vocal 2", "Kim_Vocal_2.onnx", Path("models")),
        )

        payload = serialize_downloadable_audio_models(catalog, installed)

        self.assertTrue(payload[0]["installed"])
        self.assertFalse(payload[1]["installed"])
        self.assertEqual(payload[1]["method"], MDXC_METHOD)

    def test_model_download_directories_are_isolated_by_engine(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual(
                audio_model_download_dir("VR", root),
                root / "models" / "VR_Models",
            )
            self.assertEqual(
                audio_model_download_dir("MDXC", root),
                root / "models" / "MDX_Net_Models",
            )
            self.assertEqual(
                audio_model_download_dir("Demucs", root),
                root / "models" / "Demucs_Models" / "v3_v4_repo",
            )

    def test_download_model_uses_the_isolated_runtime_and_verifies_output(self) -> None:
        model = DownloadableAudioModel(
            filename="Kim_Vocal_2.onnx",
            name="Kim Vocal 2",
            model_type="MDX",
            method=MDX_METHOD,
            stems=("vocals", "instrumental"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            python_path = root / "runtime" / "python.exe"
            python_path.parent.mkdir()
            python_path.write_bytes(b"runtime")
            runtime = AudioSeparatorRuntime(python_path)

            def fake_run(command, _report, _stop_event, **_kwargs):
                destination = Path(command[-2])
                destination.mkdir(parents=True, exist_ok=True)
                (destination / command[-1]).write_bytes(b"model")

            with patch(
                "app.audio_separation.service._run_streaming_command",
                side_effect=fake_run,
            ) as run, patch("app.audio_separation.service.guard_output_space") as guard:
                downloaded = download_audio_model(
                    model,
                    runtime=runtime,
                    managed_root=root / "managed",
                )

        self.assertEqual(downloaded.name, model.filename)
        self.assertEqual(run.call_args.args[0][0], str(python_path))
        guard.assert_called_once_with(root / "managed" / "models" / "MDX_Net_Models", minimum_mib=2 * 1024)

    def test_auto_device_prefers_cuda_then_directml(self) -> None:
        self.assertEqual(
            resolve_audio_device(
                "auto",
                MDX_METHOD,
                nvidia_available=True,
                directml_available=True,
            ),
            CUDA_AUDIO_DEVICE,
        )
        self.assertEqual(
            resolve_audio_device(
                "auto",
                MDX_METHOD,
                nvidia_available=False,
                directml_available=True,
            ),
            DIRECTML_AUDIO_DEVICE,
        )
        self.assertEqual(
            resolve_audio_device(
                "auto",
                DEMUCS_METHOD,
                nvidia_available=False,
                directml_available=True,
            ),
            CPU_AUDIO_DEVICE,
        )

    def test_custom_presets_round_trip_in_a_local_json_file(self) -> None:
        presets = {
            "My Karaoke": {
                "method": MDX_METHOD,
                "model_filename": "Kim_Vocal_2.onnx",
                "output_format": "MP3",
                "gpu_conversion": True,
                "instrumental_only": True,
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "audio_presets.json"
            save_audio_presets(path, presets)

            loaded = load_audio_presets(path)

        self.assertEqual(loaded, presets)

    def test_explicit_directml_rejects_demucs(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Demucs"):
            resolve_audio_device(
                DIRECTML_AUDIO_DEVICE,
                DEMUCS_METHOD,
                nvidia_available=False,
                directml_available=True,
            )

    def test_builds_mdx_directml_command_for_vocals_only(self) -> None:
        runtime = AudioSeparatorRuntime(Path(r"C:\runtime\python.exe"))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_dir = root / "models"
            model_dir.mkdir()
            model_path = model_dir / "Kim_Vocal_2.onnx"
            model_path.write_bytes(b"model")
            model = discover_uvr_models_from_paths_for_test(MDX_METHOD, model_path)
            options = AudioSeparationOptions(
                input_path=root / "song.mp3",
                output_dir=root / "output",
                method=MDX_METHOD,
                model_filename=model.filename,
                output_format="FLAC",
                segment_size="256",
                overlap="0.50",
                processing_device=DIRECTML_AUDIO_DEVICE,
                vocals_only=True,
            )

            command = build_audio_separator_command(
                runtime,
                options,
                model,
                root / "project",
                options.input_path,
                DIRECTML_AUDIO_DEVICE,
            )

        self.assertEqual(command[:2], [str(runtime.python_path), "-c"])
        self.assertIn("audio_separator.utils.cli", command[2])
        self.assertIn("--use_directml", command)
        self.assertEqual(command[command.index("--single_stem") + 1], "Vocals")
        self.assertEqual(command[command.index("--output_format") + 1], "FLAC")
        self.assertEqual(command[command.index("--mdx_segment_size") + 1], "256")
        self.assertEqual(command[command.index("--mdx_overlap") + 1], "0.5")
        custom_names = json.loads(command[command.index("--custom_output_names") + 1])
        self.assertEqual(custom_names["Vocals"], "song_vocals")

    def test_builds_vr_and_demucs_specific_arguments(self) -> None:
        runtime = AudioSeparatorRuntime(Path("python"))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "output"
            input_path = root / "song.wav"
            input_path.write_bytes(b"audio")

            vr_path = root / "1_HP-UVR.pth"
            vr_path.write_bytes(b"model")
            vr_model = discover_uvr_models_from_paths_for_test(VR_METHOD, vr_path)
            vr_options = AudioSeparationOptions(
                input_path=input_path,
                output_dir=output,
                method=VR_METHOD,
                model_filename=vr_model.filename,
                segment_size="320",
                overlap="10",
            )
            vr_command = build_audio_separator_command(
                runtime, vr_options, vr_model, output, input_path, CPU_AUDIO_DEVICE
            )

            demucs_path = root / "htdemucs.yaml"
            demucs_path.write_text("name: htdemucs", encoding="utf-8")
            demucs_model = discover_uvr_models_from_paths_for_test(DEMUCS_METHOD, demucs_path)
            demucs_options = AudioSeparationOptions(
                input_path=input_path,
                output_dir=output,
                method=DEMUCS_METHOD,
                model_filename=demucs_model.filename,
                segment_size="30",
                overlap="0.25",
            )
            demucs_command = build_audio_separator_command(
                runtime, demucs_options, demucs_model, output, input_path, CPU_AUDIO_DEVICE
            )

        self.assertEqual(vr_command[vr_command.index("--vr_window_size") + 1], "320")
        self.assertEqual(vr_command[vr_command.index("--vr_aggression") + 1], "10")
        self.assertEqual(
            demucs_command[demucs_command.index("--demucs_segment_size") + 1], "30"
        )
        self.assertEqual(demucs_command[demucs_command.index("--demucs_overlap") + 1], "0.25")

    def test_builds_mdxc_specific_arguments(self) -> None:
        runtime = AudioSeparatorRuntime(Path("python"))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path = root / "melband_roformer.ckpt"
            model_path.write_bytes(b"model")
            model = discover_uvr_models_from_paths_for_test(MDXC_METHOD, model_path)
            options = AudioSeparationOptions(
                input_path=root / "song.wav",
                output_dir=root / "output",
                method=MDXC_METHOD,
                model_filename=model.filename,
                segment_size="256",
                overlap="8",
            )

            command = build_audio_separator_command(
                runtime, options, model, root / "output", options.input_path, CPU_AUDIO_DEVICE
            )

        self.assertEqual(command[command.index("--mdxc_segment_size") + 1], "256")
        self.assertEqual(command[command.index("--mdxc_overlap") + 1], "8")

    def test_video_is_prepared_as_stereo_44k_audio(self) -> None:
        command = build_prepare_audio_command(
            "ffmpeg",
            Path("video.mp4"),
            Path("prepared.wav"),
            sample_mode=True,
        )

        self.assertIn("-vn", command)
        self.assertEqual(command[command.index("-ac") + 1], "2")
        self.assertEqual(command[command.index("-ar") + 1], "44100")
        self.assertEqual(command[command.index("-t") + 1], "30")

    def test_runtime_probe_checks_the_selected_directml_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            python_path = Path(temp_dir) / "python.exe"
            python_path.write_bytes(b"runtime")
            runtime = AudioSeparatorRuntime(python_path)
            completed = subprocess.CompletedProcess([], 0, "ready\n", "")
            with patch("app.audio_separation.service.subprocess.run", return_value=completed) as run:
                ready, _message = audio_separator_runtime_ready(
                    runtime,
                    DIRECTML_AUDIO_DEVICE,
                    MDX_METHOD,
                )

        self.assertTrue(ready)
        probe = run.call_args.args[0][2]
        self.assertIn("DmlExecutionProvider", probe)

    def test_streaming_command_terminates_process_when_progress_callback_fails(self) -> None:
        process = Mock()
        process.stdout = iter(["working\n"])
        process.poll.return_value = None
        stop_event = threading.Event()

        with (
            patch("app.audio_separation.service.subprocess.Popen", return_value=process),
            patch("app.audio_separation.service.managed_media_processes.ensure_running"),
            patch("app.audio_separation.service.managed_media_processes.add"),
            patch("app.audio_separation.service.managed_media_processes.discard") as discard,
            patch("app.audio_separation.service.terminate_process_tree") as terminate,
        ):
            with self.assertRaisesRegex(RuntimeError, "callback failed"):
                _run_streaming_command(
                    ["separator"],
                    lambda _message: (_ for _ in ()).throw(RuntimeError("callback failed")),
                    stop_event,
                )

        terminate.assert_called_once_with(process)
        process.wait.assert_called_once_with(timeout=5)
        discard.assert_called_once_with(process)

    def test_cannot_request_both_single_stems(self) -> None:
        runtime = AudioSeparatorRuntime(Path("python"))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path = root / "model.onnx"
            model_path.write_bytes(b"model")
            model = discover_uvr_models_from_paths_for_test(MDX_METHOD, model_path)
            options = AudioSeparationOptions(
                input_path=root / "song.wav",
                output_dir=root,
                model_filename=model.filename,
                vocals_only=True,
                instrumental_only=True,
            )

            with self.assertRaisesRegex(ValueError, "Vocals Only"):
                build_audio_separator_command(
                    runtime, options, model, root, options.input_path, CPU_AUDIO_DEVICE
                )

    def test_separation_writes_outputs_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            uvr_root = root / "uvr"
            model_dir = uvr_root / "models" / "MDX_Net_Models"
            model_dir.mkdir(parents=True)
            (model_dir / "Kim_Vocal_2.onnx").write_bytes(b"model")
            input_path = root / "song.wav"
            input_path.write_bytes(b"audio")
            output_dir = root / "output"
            runtime = AudioSeparatorRuntime(root / "runtime" / "python.exe")
            options = AudioSeparationOptions(
                input_path=input_path,
                output_dir=output_dir,
                model_filename="Kim_Vocal_2.onnx",
            )

            def fake_run(command, _report, _stop_event, **_kwargs):
                project_dir = Path(command[command.index("--output_dir") + 1])
                (project_dir / "song_(Vocals)_Kim_Vocal_2.wav").write_bytes(b"stem")
                (project_dir / "song_(Instrumental)_Kim_Vocal_2.wav").write_bytes(b"stem")

            with (
                patch("app.audio_separation.service.audio_separator_runtime_ready", return_value=(True, "ready")),
                patch("app.audio_separation.service.resolve_audio_device", return_value=CPU_AUDIO_DEVICE),
                patch("app.audio_separation.service._run_streaming_command", side_effect=fake_run),
            ):
                result = separate_audio(options, uvr_root=uvr_root, runtime=runtime)

            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(len(result.output_paths), 2)
        self.assertEqual(manifest["model"], "Kim_Vocal_2.onnx")
        self.assertEqual(manifest["device"], CPU_AUDIO_DEVICE)
        self.assertEqual(len(manifest["files"]), 2)


def discover_uvr_models_from_paths_for_test(method: str, path: Path):
    from app.audio_separation.service import UVRModel

    return UVRModel(
        method=method,
        label=path.stem.replace("_", " "),
        filename=path.name,
        model_dir=path.parent,
    )


if __name__ == "__main__":
    unittest.main()
