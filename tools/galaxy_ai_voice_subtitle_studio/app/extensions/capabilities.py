"""Read-only dispositions for advanced Galaxy voice capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Literal, Mapping


DispositionKind = Literal[
    "extension",
    "deferred",
    "optional_adapter",
    "non_goal",
]

_DISPOSITION_KINDS = frozenset(
    ("extension", "deferred", "optional_adapter", "non_goal")
)


@dataclass(frozen=True)
class AdvancedCapabilityDisposition:
    capability_id: str
    label: str
    category: str
    disposition: DispositionKind
    summary: str
    boundary: str
    constraints: tuple[str, ...] = ()
    revisit_triggers: tuple[str, ...] = ()
    extension_capability_ids: tuple[str, ...] = ()
    default_enabled: bool = False

    def __post_init__(self) -> None:
        if self.disposition not in _DISPOSITION_KINDS:
            raise ValueError(f"Unknown disposition: {self.disposition}")
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "revisit_triggers", tuple(self.revisit_triggers))
        object.__setattr__(
            self,
            "extension_capability_ids",
            tuple(self.extension_capability_ids),
        )


class AdvancedCapabilityRegistry:
    def __init__(
        self,
        capabilities: Iterable[AdvancedCapabilityDisposition] = (),
    ) -> None:
        ordered = tuple(capabilities)
        by_id: dict[str, AdvancedCapabilityDisposition] = {}
        for capability in ordered:
            if capability.capability_id in by_id:
                raise ValueError(
                    f"Capability {capability.capability_id!r} is already registered."
                )
            by_id[capability.capability_id] = capability
        self._capabilities = ordered
        self._by_id: Mapping[str, AdvancedCapabilityDisposition] = MappingProxyType(
            by_id
        )

    def list_capabilities(self) -> tuple[AdvancedCapabilityDisposition, ...]:
        return self._capabilities

    def get(self, capability_id: str) -> AdvancedCapabilityDisposition:
        capability = self._by_id.get(capability_id)
        if capability is None:
            raise KeyError(f"Unknown advanced capability: {capability_id}")
        return capability


advanced_capability_registry = AdvancedCapabilityRegistry(
    (
        AdvancedCapabilityDisposition(
            capability_id="dictation.live",
            label="Live dictation",
            category="voice_input",
            disposition="extension",
            summary="Capture microphone speech as text in other applications.",
            boundary=(
                "Reuse the Transcript ASR adapter while keeping microphone capture, "
                "global hotkeys, and auto-paste outside core Transcripts."
            ),
            constraints=(
                "Microphone access requires an explicit operating-system permission.",
                "Global hotkeys and auto-paste must be opt-in and independently disabled.",
            ),
            revisit_triggers=(
                "A supported cross-platform capture and hotkey contract is available.",
                "User demand justifies a dedicated hands-free transcription workflow.",
            ),
            extension_capability_ids=("asr.faster-whisper",),
        ),
        AdvancedCapabilityDisposition(
            capability_id="transcripts.local_refinement",
            label="Local transcript refinement",
            category="transcripts",
            disposition="extension",
            summary="Optionally refine transcript text with a local AI provider.",
            boundary=(
                "Reuse the shared translation and AI provider contract without making "
                "refinement a dependency of transcription."
            ),
            constraints=(
                "Core transcription must remain usable when refinement is unavailable.",
                "Source timing and speaker data must survive text refinement.",
            ),
            revisit_triggers=(
                "The local provider contract supports structured transcript edits.",
                "Quality fixtures show repeatable improvement without timing loss.",
            ),
            extension_capability_ids=("translation.ollama",),
        ),
        AdvancedCapabilityDisposition(
            capability_id="api.openai_audio",
            label="OpenAI-compatible local audio API",
            category="developer_api",
            disposition="extension",
            summary="Expose stabilized Galaxy speech contracts through a local API.",
            boundary=(
                "Build over Galaxy TTS, ASR, and Voice Library contracts instead of "
                "accessing engines directly."
            ),
            constraints=(
                "The service must bind to loopback by default.",
                "Remote exposure requires explicit authentication and secret redaction.",
            ),
            revisit_triggers=(
                "Galaxy TTS, ASR, and Voice Library contracts are stable.",
                "Compatibility fixtures define the supported OpenAI audio surface.",
            ),
            extension_capability_ids=(
                "tts.edge",
                "tts.sapi",
                "tts.omnivoice",
                "asr.faster-whisper",
            ),
        ),
        AdvancedCapabilityDisposition(
            capability_id="mcp.voice",
            label="MCP voice bindings",
            category="automation",
            disposition="extension",
            summary="Offer voice operations to MCP clients through the local audio API.",
            boundary=(
                "Build over the local audio API with no separate creative workspace or "
                "direct engine access."
            ),
            constraints=(
                "MCP calls must inherit Galaxy authentication and secret redaction.",
                "Bindings cannot bypass API capability or consent checks.",
            ),
            revisit_triggers=(
                "The local audio API has a stable authenticated contract.",
                "A concrete MCP client workflow has end-to-end acceptance fixtures.",
            ),
        ),
        AdvancedCapabilityDisposition(
            capability_id="backend.remote",
            label="Remote backend",
            category="deployment",
            disposition="deferred",
            summary="Run Galaxy voice services beyond the local desktop boundary.",
            boundary="Keep the current desktop service on its loopback boundary.",
            constraints=(
                "Remote access needs authentication, TLS, secret storage, and revocation.",
                "A dedicated remote threat model must precede implementation.",
            ),
            revisit_triggers=(
                "A remote deployment threat model and ownership plan are approved.",
                "Authentication, TLS, secret storage, and revocation designs are accepted.",
            ),
        ),
        AdvancedCapabilityDisposition(
            capability_id="audio.watermarking",
            label="Audio watermarking",
            category="provenance",
            disposition="optional_adapter",
            summary="Apply an optional provenance mark to generated audio.",
            boundary="Integrate only through a separately licensed provenance adapter.",
            constraints=(
                "The implementation requires a fresh compatibility and license review.",
                "Provenance must record applied, unavailable, and failed outcomes.",
            ),
            revisit_triggers=(
                "A compatible implementation passes license review.",
                "A provenance format and verification workflow are approved.",
            ),
        ),
        AdvancedCapabilityDisposition(
            capability_id="video.visual_lip_sync",
            label="Visual lip-sync",
            category="video",
            disposition="optional_adapter",
            summary="Synchronize visible mouth motion with generated speech.",
            boundary=(
                "Keep visual synthesis separate from Galaxy Audio Lip-Sync and isolate "
                "it behind an optional adapter."
            ),
            constraints=(
                "Each model and implementation requires an independent license review.",
                "GPU and runtime dependencies must be isolated from native Dubbing.",
            ),
            revisit_triggers=(
                "A suitable model passes quality, runtime, and license review.",
                "Visual synthesis has an isolated GPU scheduling contract.",
            ),
        ),
        AdvancedCapabilityDisposition(
            capability_id="marketplace.plugins",
            label="Plugin marketplace",
            category="ecosystem",
            disposition="non_goal",
            summary="Publish, discover, and execute third-party Galaxy extensions.",
            boundary=(
                "Public discovery, publishing, payments, and third-party code execution "
                "remain outside the local-first desktop product."
            ),
            constraints=(
                "Marketplace execution is not a protected Galaxy extension boundary.",
                "Local Voice Library import and export remain separate capabilities.",
            ),
            revisit_triggers=(
                "Only a new product decision can change this explicit non-goal.",
            ),
        ),
    )
)
