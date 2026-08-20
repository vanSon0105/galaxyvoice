from __future__ import annotations

import threading
from pathlib import Path

from .client import OmniVoiceWorkerClient
from .runtime import OmniVoiceRuntime


_lock = threading.Lock()
_client: OmniVoiceWorkerClient | None = None


def get_shared_worker_client(
    runtime: OmniVoiceRuntime,
    worker_path: Path,
) -> OmniVoiceWorkerClient:
    """Return the one resident OmniVoice worker shared by all web workspaces."""
    global _client
    with _lock:
        if _client is None:
            _client = OmniVoiceWorkerClient(runtime, worker_path)
        return _client


def shutdown_shared_worker_client() -> None:
    global _client
    with _lock:
        client = _client
        _client = None
    if client is not None:
        client.close()
