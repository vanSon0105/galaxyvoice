from __future__ import annotations

from pathlib import Path

from ..omnivoice.service import WorkerClient
from ..studio.models import StudioGenerationSpec
from ..studio.omnivoice_adapter import OmniVoiceStudioAdapter
from ..studio.service import ProgressCallback


class OmniVoiceBatchAdapter(OmniVoiceStudioAdapter):
    max_parallelism = 1

    def __init__(self, client: WorkerClient, profiles_dir: Path) -> None:
        super().__init__(client, profiles_dir)

    def prewarm(
        self,
        spec: StudioGenerationSpec,
        progress: ProgressCallback | None = None,
    ) -> None:
        if progress:
            progress("Đang nạp trước model OmniVoice...")
        advanced = spec.engine_options
        self.client.request(
            "load",
            {
                "model_id": spec.model_id,
                "device": spec.device,
                "lora_adapter": str(advanced.get("lora_adapter") or ""),
                "enable_flashinfer": bool(advanced.get("enable_flashinfer", False)),
                "flashinfer_cuda_graph": bool(advanced.get("flashinfer_cuda_graph", True)),
            },
            on_progress=progress,
        )
