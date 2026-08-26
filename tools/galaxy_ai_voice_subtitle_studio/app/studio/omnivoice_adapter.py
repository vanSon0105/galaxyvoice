from __future__ import annotations

from pathlib import Path
from typing import Any

from ..omnivoice.models import (
    AUTO_MODE,
    CLONE_MODE,
    DESIGN_MODE,
    OmniVoiceGenerationOptions,
)
from ..omnivoice.service import WorkerClient, generate_omnivoice_audio
from .models import StudioArtifact, StudioGenerationSpec
from .service import ProgressCallback


class OmniVoiceStudioAdapter:
    engine_id = "omnivoice"

    def __init__(self, client: WorkerClient, profiles_dir: Path) -> None:
        self.client = client
        self.profiles_dir = profiles_dir

    def generate(
        self,
        spec: StudioGenerationSpec,
        progress: ProgressCallback | None = None,
    ) -> StudioArtifact:
        source = spec.voice.source
        mode = DESIGN_MODE if source == "design" else CLONE_MODE if source in ("profile", "reference") else AUTO_MODE
        advanced = spec.engine_options
        result = generate_omnivoice_audio(
            OmniVoiceGenerationOptions(
                mode=mode,
                text=spec.text,
                output_dir=Path(spec.output_dir).expanduser(),
                project_name=spec.output_name or "studio-take",
                model_id=spec.model_id,
                device=spec.device,
                language=spec.language,
                reference_audio=Path(spec.voice.reference_audio).expanduser()
                if spec.voice.reference_audio
                else None,
                reference_text=spec.voice.reference_text,
                profile_id=spec.voice.profile_id,
                save_profile_name=spec.voice.save_profile_name,
                profiles_dir=self.profiles_dir,
                instruct=spec.voice.instruction,
                num_step=int(advanced.get("num_step", 32)),
                guidance_scale=float(advanced.get("guidance_scale", 2.0)),
                t_shift=float(advanced.get("t_shift", 0.1)),
                speed=spec.speed,
                duration=spec.duration,
                denoise=bool(advanced.get("denoise", True)),
                normalize_text=bool(advanced.get("normalize_text", False)),
                preprocess_prompt=bool(advanced.get("preprocess_prompt", True)),
                postprocess_output=bool(advanced.get("postprocess_output", True)),
                export_mp3="mp3" in spec.formats,
            ),
            self.client,
            progress=progress,
        )
        return StudioArtifact(
            project_dir=result.project_dir,
            wav_path=result.wav_path,
            mp3_path=result.mp3_path,
            manifest_path=result.manifest_path,
            profile_id=result.profile_id,
            warnings=result.warnings,
        )
