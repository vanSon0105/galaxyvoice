from __future__ import annotations

import dataclasses
import unittest
from typing import cast, get_args

from app.extensions import (
    AdvancedCapabilityDisposition,
    AdvancedCapabilityRegistry,
    DispositionKind,
    advanced_capability_registry,
)
from app.runtime.defaults import capability_registry


def disposition(
    capability_id: str,
    *,
    kind: DispositionKind = "extension",
) -> AdvancedCapabilityDisposition:
    return AdvancedCapabilityDisposition(
        capability_id=capability_id,
        label=capability_id,
        category="test",
        disposition=kind,
        summary="Test summary.",
        boundary="Test boundary.",
        constraints=("Test constraint.",),
        revisit_triggers=("Test trigger.",),
    )


class AdvancedCapabilityRegistryTests(unittest.TestCase):
    def test_default_registry_has_exact_capabilities_in_product_order(self) -> None:
        self.assertEqual(
            tuple(
                item.capability_id
                for item in advanced_capability_registry.list_capabilities()
            ),
            (
                "dictation.live",
                "transcripts.local_refinement",
                "api.openai_audio",
                "mcp.voice",
                "backend.remote",
                "audio.watermarking",
                "video.visual_lip_sync",
                "marketplace.plugins",
            ),
        )

    def test_registry_preserves_insertion_order_and_supports_lookup(self) -> None:
        second = disposition("extension.second")
        first = disposition("extension.first")
        registry = AdvancedCapabilityRegistry((second, first))

        self.assertEqual(registry.list_capabilities(), (second, first))
        self.assertIs(registry.get("extension.first"), first)

    def test_registry_rejects_duplicate_capability_ids(self) -> None:
        duplicate = disposition("extension.duplicate")

        with self.assertRaisesRegex(ValueError, "already registered"):
            AdvancedCapabilityRegistry((duplicate, duplicate))

    def test_disposition_kind_is_limited_to_approved_values(self) -> None:
        self.assertEqual(
            get_args(DispositionKind),
            ("extension", "deferred", "optional_adapter", "non_goal"),
        )

        with self.assertRaisesRegex(ValueError, "Unknown disposition"):
            disposition("extension.invalid", kind=cast(DispositionKind, "native"))

    def test_default_capabilities_have_approved_dispositions(self) -> None:
        self.assertEqual(
            {
                item.capability_id: item.disposition
                for item in advanced_capability_registry.list_capabilities()
            },
            {
                "dictation.live": "extension",
                "transcripts.local_refinement": "extension",
                "api.openai_audio": "extension",
                "mcp.voice": "extension",
                "backend.remote": "deferred",
                "audio.watermarking": "optional_adapter",
                "video.visual_lip_sync": "optional_adapter",
                "marketplace.plugins": "non_goal",
            },
        )

    def test_default_capabilities_are_disabled_and_immutable(self) -> None:
        capabilities = advanced_capability_registry.list_capabilities()

        self.assertTrue(all(not item.default_enabled for item in capabilities))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            capabilities[0].default_enabled = True

    def test_extension_runtime_references_are_known_capability_ids(self) -> None:
        known_runtime_ids = {
            item.capability_id for item in capability_registry.list_capabilities()
        }
        extensions = {
            item.capability_id: item.extension_capability_ids
            for item in advanced_capability_registry.list_capabilities()
            if item.disposition == "extension"
        }

        self.assertEqual(
            extensions,
            {
                "dictation.live": ("asr.faster-whisper",),
                "transcripts.local_refinement": ("translation.ollama",),
                "api.openai_audio": (
                    "tts.edge",
                    "tts.sapi",
                    "tts.omnivoice",
                    "asr.faster-whisper",
                ),
                "mcp.voice": (),
            },
        )
        self.assertTrue(
            all(
                runtime_id in known_runtime_ids
                for runtime_ids in extensions.values()
                for runtime_id in runtime_ids
            )
        )


if __name__ == "__main__":
    unittest.main()
