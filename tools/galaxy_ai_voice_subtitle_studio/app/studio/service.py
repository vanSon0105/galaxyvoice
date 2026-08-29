from __future__ import annotations

from typing import Callable, Protocol

from ..reliability.service import estimate_audio_bytes, guard_output_space
from .models import StudioArtifact, StudioGenerationSpec, StudioTakeView
from .repository import StudioTakeRepository


ProgressCallback = Callable[[str], None]


class StudioEngine(Protocol):
    engine_id: str

    def generate(
        self,
        spec: StudioGenerationSpec,
        progress: ProgressCallback | None = None,
    ) -> StudioArtifact: ...


class StudioService:
    def __init__(self, repository: StudioTakeRepository) -> None:
        self.repository = repository

    def generate(
        self,
        spec: StudioGenerationSpec,
        engine: StudioEngine,
        *,
        progress: ProgressCallback | None = None,
        rerun_of: str = "",
        generation_run_id: str,
    ) -> StudioTakeView:
        spec.validate()
        guard_output_space(
            spec.output_dir,
            required_bytes=estimate_audio_bytes(spec.text, output_count=len(spec.formats)),
        )
        if engine.engine_id != spec.engine_id:
            raise ValueError(
                f"Adapter {engine.engine_id} không thể xử lý yêu cầu cho {spec.engine_id}."
            )
        artifact = engine.generate(spec, progress)
        return self.repository.add(
            spec,
            artifact,
            generation_run_id=generation_run_id,
            rerun_of=rerun_of,
        )
