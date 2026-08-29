from __future__ import annotations

import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from subprocess import CompletedProcess

from app.audio_postproduction.models import (
    AudioExportRequest,
    AudioPostChain,
    AudioSource,
    ExportMetadata,
    SegmentGain,
)
from app.audio_postproduction.service import AudioPostproductionService
from app.common.errors import TaskCancelledError


def _write_wav(path: Path, *, frames: int = 8_000, sample_rate: int = 8_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = bytearray()
    for index in range(frames):
        value = 12_000 if (index // 200) % 2 == 0 else -6_000
        samples.extend(int(value).to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(samples))


class AudioPostproductionServiceTests(unittest.TestCase):
    def test_export_honors_cancellation_before_starting_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory) / "project"
            source = project_dir / "voice.wav"
            _write_wav(source)
            stop_event = threading.Event()
            stop_event.set()
            service = AudioPostproductionService(
                ffmpeg="ffmpeg",
                runner=lambda command: CompletedProcess(command, 0, "", ""),
            )

            with self.assertRaises(TaskCancelledError):
                service.export(
                    AudioExportRequest(
                        project_id="p",
                        workflow_id="take-1",
                        workspace="studio",
                        project_dir=project_dir,
                        title="take",
                        sources=(AudioSource("voice", source),),
                    ),
                    stop_event=stop_event,
                )

    def test_waveform_is_bounded_and_reuses_project_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory) / "project"
            source = project_dir / "takes" / "voice.wav"
            _write_wav(source)
            service = AudioPostproductionService(ffmpeg="ffmpeg", ffprobe="ffprobe")

            first = service.waveform(source, project_dir=project_dir, points=64)
            second = service.waveform(source, project_dir=project_dir, points=64)

            self.assertEqual(len(first.peaks), 64)
            self.assertEqual(first.duration_ms, 1_000)
            self.assertTrue(first.cache_path.is_relative_to(project_dir))
            self.assertEqual(first.cache_path, second.cache_path)
            self.assertEqual(first.peaks, second.peaks)

    def test_export_builds_engine_neutral_chain_and_trace_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory) / "project"
            voice = project_dir / "takes" / "voice.wav"
            music = Path(directory) / "linked" / "music.wav"
            _write_wav(voice)
            _write_wav(music)
            commands: list[list[str]] = []

            def fake_run(command: list[str]) -> CompletedProcess[str]:
                commands.append(command)
                output = Path(command[-1])
                if output.suffix in {".wav", ".mp3", ".flac", ".m4a"}:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"audio")
                return CompletedProcess(command, 0, "", "")

            service = AudioPostproductionService(
                ffmpeg="ffmpeg",
                ffprobe="ffprobe",
                runner=fake_run,
                probe=lambda _path: {"duration_ms": 1_000, "sample_rate": 8_000, "channels": 1},
            )
            request = AudioExportRequest(
                project_id="project-1",
                workflow_id="dub-1",
                workspace="dubbing",
                project_dir=project_dir,
                title="Final dub",
                sources=(
                    AudioSource("voice", voice, role="voice", gain_db=1.5),
                    AudioSource("music", music, role="background", gain_db=-8.0),
                ),
                formats=("wav", "mp3", "flac"),
                chain=AudioPostChain(
                    trim_start_ms=100,
                    trim_end_ms=900,
                    gain_db=-1.0,
                    segment_gains=(SegmentGain(200, 400, 2.5),),
                    fade_in_ms=50,
                    fade_out_ms=80,
                    normalize=True,
                    preset="voice_clean",
                    trim_silence=True,
                ),
                metadata=ExportMetadata(title="Final dub", artist="Galaxy"),
            )

            result = service.export(request)

            self.assertEqual(set(result.files), {"wav", "mp3", "flac"})
            self.assertTrue(all(path.is_relative_to(project_dir) for path in result.files.values()))
            self.assertTrue(result.manifest_path.is_file())
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["project_id"], "project-1")
            self.assertEqual(manifest["workspace"], "dubbing")
            self.assertEqual(manifest["sources"][0]["path"], "takes/voice.wav")
            self.assertEqual(manifest["sources"][1]["path_kind"], "linked")
            self.assertEqual(set(manifest["files"]), {"wav", "mp3", "flac"})
            filter_command = " ".join(commands[0])
            self.assertIn("atrim=start=0.100000:end=0.900000", filter_command)
            self.assertIn("volume=1.5dB", filter_command)
            self.assertIn("between(t,0.200000,0.400000)", filter_command)
            self.assertIn("amix=inputs=2", filter_command)
            self.assertEqual(filter_command.count("areverse"), 4)
            self.assertNotIn("stop_periods=-1", filter_command)
            self.assertTrue(any("title=Final dub" in " ".join(command) for command in commands[1:]))

            discovered = service.discover_sources(project_dir)
            self.assertIn(voice.resolve(), {source.path.resolve() for source in discovered})
            self.assertNotIn(next(iter(result.files.values())).resolve(), {source.path.resolve() for source in discovered})

    def test_export_rejects_output_path_that_is_not_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_path = root / "not-a-directory"
            project_path.write_text("x", encoding="utf-8")
            source = root / "voice.wav"
            _write_wav(source)
            service = AudioPostproductionService(ffmpeg="ffmpeg", ffprobe="ffprobe")
            with self.assertRaises(ValueError):
                service.export(
                    AudioExportRequest(
                        project_id="p",
                        workflow_id="take-1",
                        workspace="studio",
                        project_dir=project_path,
                        title="take",
                        sources=(AudioSource("voice", source),),
                    )
                )

    def test_failed_export_removes_partial_artifacts_and_rejects_unsafe_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory) / "project"
            source = project_dir / "voice.wav"
            _write_wav(source)
            service = AudioPostproductionService(
                ffmpeg="ffmpeg",
                runner=lambda command: CompletedProcess(command, 1, "", "failed"),
            )

            with self.assertRaises(RuntimeError):
                service.export(
                    AudioExportRequest(
                        project_id="p",
                        workflow_id="take-1",
                        workspace="studio",
                        project_dir=project_dir,
                        title="take",
                        sources=(AudioSource("voice", source),),
                    )
                )

            export_root = project_dir / "exports" / "audio"
            self.assertFalse(any(export_root.iterdir()) if export_root.is_dir() else False)
            with self.assertRaises(ValueError):
                service.resolve_export(project_dir, "../outside", "wav")
            with self.assertRaises(ValueError):
                service.export(
                    AudioExportRequest(
                        project_id="another-project",
                        workflow_id="take-2",
                        workspace="studio",
                        project_dir=project_dir,
                        title="take",
                        sources=(AudioSource("voice", source),),
                    )
                )


if __name__ == "__main__":
    unittest.main()
