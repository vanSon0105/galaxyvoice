from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.server.main import create_app


class ExtensionCapabilitiesApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        self.client.close()

    def test_catalogue_returns_complete_ordered_response_shape(self) -> None:
        response = self.client.get("/api/extensions/capabilities")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {"capabilities"})
        self.assertEqual(len(body["capabilities"]), 8)
        self.assertEqual(
            [item["capability_id"] for item in body["capabilities"]],
            [
                "dictation.live",
                "transcripts.local_refinement",
                "api.openai_audio",
                "mcp.voice",
                "backend.remote",
                "audio.watermarking",
                "video.visual_lip_sync",
                "marketplace.plugins",
            ],
        )
        expected_fields = {
            "capability_id",
            "label",
            "category",
            "disposition",
            "summary",
            "boundary",
            "constraints",
            "revisit_triggers",
            "extension_capability_ids",
            "default_enabled",
        }
        self.assertTrue(
            all(set(item) == expected_fields for item in body["capabilities"])
        )
        self.assertEqual(
            body["capabilities"][0],
            {
                "capability_id": "dictation.live",
                "label": "Live dictation",
                "category": "voice_input",
                "disposition": "extension",
                "summary": "Capture microphone speech as text in other applications.",
                "boundary": (
                    "Reuse the Transcript ASR adapter while keeping microphone capture, "
                    "global hotkeys, and auto-paste outside core Transcripts."
                ),
                "constraints": [
                    "Microphone access requires an explicit operating-system permission.",
                    "Global hotkeys and auto-paste must be opt-in and independently disabled.",
                ],
                "revisit_triggers": [
                    "A supported cross-platform capture and hotkey contract is available.",
                    "User demand justifies a dedicated hands-free transcription workflow.",
                ],
                "extension_capability_ids": ["asr.faster-whisper"],
                "default_enabled": False,
            },
        )

    def test_catalogue_does_not_expose_a_mutation_method(self) -> None:
        response = self.client.post("/api/extensions/capabilities", json={})

        self.assertEqual(response.status_code, 405)

    def test_catalogue_has_an_explicit_openapi_contract(self) -> None:
        schema = self.client.get("/openapi.json").json()
        response_schema = schema["paths"]["/api/extensions/capabilities"]["get"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(
            response_schema,
            {"$ref": "#/components/schemas/ExtensionCapabilitiesResponse"},
        )

        capability_schema = schema["components"]["schemas"][
            "ExtensionCapabilityResponse"
        ]
        self.assertEqual(
            set(capability_schema["properties"]),
            {
                "capability_id",
                "label",
                "category",
                "disposition",
                "summary",
                "boundary",
                "constraints",
                "revisit_triggers",
                "extension_capability_ids",
                "default_enabled",
            },
        )
        self.assertFalse(capability_schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
