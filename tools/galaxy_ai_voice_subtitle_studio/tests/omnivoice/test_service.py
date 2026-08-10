from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from app.omnivoice.models import AUTO_MODE, DESIGN_MODE, OmniVoiceGenerationOptions
from app.omnivoice.service import generate_omnivoice_audio


class _FakeClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    def request(self, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
        self.requests.append((command, payload))
        output_path = Path(str(payload["output_path"]))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(24_000)
            target.writeframes(b"\x00\x00" * 2_400)
        return {"output_path": str(output_path), "sample_rate": 24_000}


class OmniVoiceServiceTests(unittest.TestCase):
    def test_generation_creates_project_and_manifest(self) -> None:
        client = _FakeClient()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate_omnivoice_audio(
                OmniVoiceGenerationOptions(
                    mode=AUTO_MODE,
                    text="Xin chào",
                    output_dir=Path(temp_dir),
                    project_name="voice-test",
                    language="vi",
                    guidance_scale=0.0,
                    layer_penalty_factor=0.0,
                    position_temperature=0.0,
                    enable_flashinfer=True,
                    flashinfer_cuda_graph=False,
                    lora_adapter="C:/models/adapter",
                ),
                client,
            )

            self.assertTrue(result.wav_path.is_file())
            self.assertTrue(result.manifest_path.is_file())
            self.assertEqual(client.requests[0][0], "generate")
            self.assertEqual(client.requests[0][1]["language"], "vi")
            self.assertEqual(client.requests[0][1]["guidance_scale"], 0.0)
            self.assertEqual(client.requests[0][1]["layer_penalty_factor"], 0.0)
            self.assertEqual(client.requests[0][1]["position_temperature"], 0.0)
            self.assertTrue(client.requests[0][1]["enable_flashinfer"])
            self.assertFalse(client.requests[0][1]["flashinfer_cuda_graph"])
            self.assertEqual(client.requests[0][1]["lora_adapter"], "C:/models/adapter")

    def test_blank_text_is_rejected_before_starting_worker(self) -> None:
        client = _FakeClient()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            with self.assertRaises(ValueError):
                generate_omnivoice_audio(
                    OmniVoiceGenerationOptions(
                        mode=AUTO_MODE,
                        text="   ",
                        output_dir=output_dir,
                    ),
                    client,
                )
            self.assertEqual(list(output_dir.iterdir()), [])
        self.assertEqual(client.requests, [])

    def test_blank_design_is_rejected_without_creating_project(self) -> None:
        client = _FakeClient()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            with self.assertRaises(ValueError):
                generate_omnivoice_audio(
                    OmniVoiceGenerationOptions(
                        mode=DESIGN_MODE,
                        text="Xin chào",
                        output_dir=output_dir,
                    ),
                    client,
                )

            self.assertEqual(list(output_dir.iterdir()), [])
        self.assertEqual(client.requests, [])


if __name__ == "__main__":
    unittest.main()
