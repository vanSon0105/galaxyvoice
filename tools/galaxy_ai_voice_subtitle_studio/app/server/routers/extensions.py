"""Read-only HTTP surface for advanced capability dispositions."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from ...extensions.capabilities import advanced_capability_registry


router = APIRouter(prefix="/api/extensions", tags=["extensions"])


@router.get("/capabilities")
def list_capabilities() -> dict[str, list[dict[str, Any]]]:
    return {
        "capabilities": [
            asdict(capability)
            for capability in advanced_capability_registry.list_capabilities()
        ]
    }
