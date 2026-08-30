"""Read-only HTTP surface for advanced capability dispositions."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from ...extensions.capabilities import DispositionKind, advanced_capability_registry


router = APIRouter(prefix="/api/extensions", tags=["extensions"])


class ExtensionCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    label: str
    category: str
    disposition: DispositionKind
    summary: str
    boundary: str
    constraints: list[str]
    revisit_triggers: list[str]
    extension_capability_ids: list[str]
    default_enabled: bool


class ExtensionCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[ExtensionCapabilityResponse]


@router.get("/capabilities", response_model=ExtensionCapabilitiesResponse)
def list_capabilities() -> ExtensionCapabilitiesResponse:
    return ExtensionCapabilitiesResponse(
        capabilities=[
            ExtensionCapabilityResponse(
                capability_id=capability.capability_id,
                label=capability.label,
                category=capability.category,
                disposition=capability.disposition,
                summary=capability.summary,
                boundary=capability.boundary,
                constraints=list(capability.constraints),
                revisit_triggers=list(capability.revisit_triggers),
                extension_capability_ids=list(capability.extension_capability_ids),
                default_enabled=capability.default_enabled,
            )
            for capability in advanced_capability_registry.list_capabilities()
        ]
    )
