from __future__ import annotations

from pathlib import Path

from ..studio.models import StudioArtifact, StudioGenerationSpec
from ..studio.service import ProgressCallback
from ..voice.engine import GenerationOptions, generate_package
from ..voice.tts import TTSEngine


class SystemVoiceBatchAdapter:
    max_parallelism = 8

    def __init__(self, engine: TTSEngine, voice_name: str) -> None:
        self.engine = engine
        self.engine_id = engine.code
        self.voice_name = voice_name

    def prewarm(
        self,
        _spec: StudioGenerationSpec,
        progress: ProgressCallback | None = None,
    ) -> None:
        if progress:
            progress(f"Đang kiểm tra {self.engine.label}...")
        if not self.engine.available():
            raise RuntimeError(self.engine.unavailable_reason() or f"{self.engine.label} chưa sẵn sàng.")

    def generate(
        self,
        spec: StudioGenerationSpec,
        progress: ProgressCallback | None = None,
    ) -> StudioArtifact:
        rate = max(-10, min(10, round((spec.speed - 1.0) * 10)))
        result = generate_package(
            GenerationOptions(
                text=spec.text,
                output_dir=Path(spec.output_dir),
                project_name=spec.output_name,
                voice_name=self.voice_name,
                rate=rate,
                volume=int(spec.engine_options.get("volume", 100)),
                pause_ms=max(0, int(spec.engine_options.get("_galaxy_cluster_pause_ms", 0))),
                max_chars=max(20, int(spec.engine_options.get("max_chars", 160))),
                export_mp3="mp3" in spec.formats,
                keep_segments=False,
            ),
            tts=self.engine,
            progress=progress,
        )
        warnings = list(result.warnings)
        if spec.duration is not None:
            warnings.append("Giọng hệ thống không hỗ trợ ép thời lượng; audio giữ tốc độ đã chọn.")
        return StudioArtifact(
            project_dir=result.project_dir,
            wav_path=result.wav_path,
            mp3_path=result.mp3_path,
            manifest_path=result.manifest_path,
            warnings=tuple(warnings),
        )
