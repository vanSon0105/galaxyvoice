from __future__ import annotations

import unittest

from app.runtime.capabilities import (
    CapabilityDescriptor,
    CapabilityRegistry,
    FunctionCapabilityAdapter,
    PreflightRequest,
    PreflightResult,
)
from app.runtime.models import (
    FunctionModelAdapter,
    ModelDescriptor,
    ModelRegistry,
)


class CapabilityRegistryTests(unittest.TestCase):
    def test_lists_descriptors_and_routes_preflight_to_adapter(self) -> None:
        descriptor = CapabilityDescriptor(
            capability_id="tts.test",
            kind="tts",
            label="Test TTS",
            runtime_id="test-runtime",
            devices=("cpu",),
            default_device="cpu",
            resumable=False,
            installable=True,
        )
        registry = CapabilityRegistry()
        registry.register(
            FunctionCapabilityAdapter(
                descriptor,
                lambda request: PreflightResult.ready(
                    request.capability_id,
                    requested_device=request.device,
                    resolved_device="cpu",
                    message="ready",
                ),
            )
        )

        self.assertEqual(registry.list_capabilities(), (descriptor,))
        result = registry.preflight(PreflightRequest("tts.test", device="auto"))
        self.assertTrue(result.ready)
        self.assertEqual(result.resolved_device, "cpu")

    def test_duplicate_capability_is_rejected(self) -> None:
        descriptor = CapabilityDescriptor(
            capability_id="tts.test",
            kind="tts",
            label="Test TTS",
            runtime_id="test-runtime",
            devices=("cpu",),
            default_device="cpu",
        )
        registry = CapabilityRegistry()
        adapter = FunctionCapabilityAdapter(
            descriptor,
            lambda request: PreflightResult.ready(request.capability_id),
        )
        registry.register(adapter)

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(adapter)

    def test_probe_exception_becomes_structured_error(self) -> None:
        descriptor = CapabilityDescriptor(
            capability_id="asr.test",
            kind="asr",
            label="Test ASR",
            runtime_id="test-runtime",
            devices=("cpu",),
            default_device="cpu",
        )
        registry = CapabilityRegistry()
        registry.register(
            FunctionCapabilityAdapter(
                descriptor,
                lambda _request: (_ for _ in ()).throw(RuntimeError("runtime missing")),
            )
        )

        result = registry.preflight(PreflightRequest("asr.test"))

        self.assertFalse(result.ready)
        self.assertEqual(result.state, "error")
        self.assertIn("runtime missing", result.message)


class ModelRegistryTests(unittest.TestCase):
    def test_model_adapter_lists_and_installs_models(self) -> None:
        installed: list[str] = []
        descriptor = ModelDescriptor(
            model_id="voice-small",
            capability_id="tts.test",
            label="Voice Small",
            installed=False,
            version="1",
        )
        registry = ModelRegistry()
        registry.register(
            FunctionModelAdapter(
                "tts.test",
                list_models=lambda _refresh: (descriptor,),
                install_model=lambda model_id, _context: installed.append(model_id) or descriptor,
            )
        )

        self.assertEqual(registry.list_models("tts.test"), (descriptor,))
        self.assertEqual(registry.install("tts.test", "voice-small", None), descriptor)
        self.assertEqual(installed, ["voice-small"])


if __name__ == "__main__":
    unittest.main()
