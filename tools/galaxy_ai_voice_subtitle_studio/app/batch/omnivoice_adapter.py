from __future__ import annotations

from pathlib import Path

from ..omnivoice.service import WorkerClient
from ..studio.omnivoice_adapter import OmniVoiceStudioAdapter


class OmniVoiceBatchAdapter(OmniVoiceStudioAdapter):
    def __init__(self, client: WorkerClient, profiles_dir: Path) -> None:
        super().__init__(client, profiles_dir)
