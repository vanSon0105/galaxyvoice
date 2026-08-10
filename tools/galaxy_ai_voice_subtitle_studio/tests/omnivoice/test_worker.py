from __future__ import annotations

import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.omnivoice import worker


class OmniVoiceWorkerEncodingTests(unittest.TestCase):
    def test_send_supports_vietnamese_when_stdout_uses_cp1252(self) -> None:
        output = io.BytesIO()
        cp1252_stdout = io.TextIOWrapper(output, encoding="cp1252")

        with patch.object(worker.sys, "__stdout__", cp1252_stdout):
            worker._send("job-1", "progress", {"message": "Đang tải model"})
            cp1252_stdout.flush()

        message = json.loads(output.getvalue().decode("ascii"))
        self.assertEqual(message["payload"]["message"], "Đang tải model")


class OmniVoiceAudioFinalizationTests(unittest.TestCase):
    def test_trim_removes_model_edge_silence_then_adds_exact_padding(self) -> None:
        audio = np.concatenate(
            [
                np.zeros(100, dtype=np.float32),
                np.full(1_000, 0.5, dtype=np.float32),
                np.zeros(200, dtype=np.float32),
            ]
        )

        result = worker._finalize_generated_audio(
            audio,
            1_000,
            trim_edges=True,
            pad_duration=0.05,
            fade_duration=0.0,
        )

        self.assertEqual(result.shape, (1_100,))
        np.testing.assert_array_equal(result[:50], np.zeros(50, dtype=np.float32))
        np.testing.assert_array_equal(result[-50:], np.zeros(50, dtype=np.float32))
        self.assertEqual(float(result[50]), 0.5)
        self.assertEqual(float(result[-51]), 0.5)

    def test_disabled_trim_preserves_model_edge_silence(self) -> None:
        audio = np.concatenate(
            [
                np.zeros(10, dtype=np.float32),
                np.ones(20, dtype=np.float32),
                np.zeros(10, dtype=np.float32),
            ]
        )

        result = worker._finalize_generated_audio(
            audio,
            1_000,
            trim_edges=False,
            pad_duration=0.0,
            fade_duration=0.0,
        )

        np.testing.assert_array_equal(result, audio)


class OmniVoiceModelLoadingTests(unittest.TestCase):
    def tearDown(self) -> None:
        worker._model = None
        worker._model_identity = None

    def test_flashinfer_failure_unloads_partially_loaded_model(self) -> None:
        class FakeAccelerator:
            @staticmethod
            def is_available() -> bool:
                return True

            @staticmethod
            def empty_cache() -> None:
                return None

        class FakeModel:
            sampling_rate = 24_000

        class FakeOmniVoice:
            @staticmethod
            def from_pretrained(*_args: object, **_kwargs: object) -> FakeModel:
                return FakeModel()

        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = FakeAccelerator()  # type: ignore[attr-defined]
        fake_torch.float16 = "float16"  # type: ignore[attr-defined]
        fake_torch.float32 = "float32"  # type: ignore[attr-defined]
        fake_omnivoice = types.ModuleType("omnivoice")
        fake_omnivoice.OmniVoice = FakeOmniVoice  # type: ignore[attr-defined]
        fake_models = types.ModuleType("omnivoice.models")
        fake_flashinfer = types.ModuleType("omnivoice.models.omnivoice_flashinfer")

        def fail_flashinfer(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("FlashInfer setup failed")

        fake_flashinfer.apply_flashinfer = fail_flashinfer  # type: ignore[attr-defined]
        modules = {
            "torch": fake_torch,
            "omnivoice": fake_omnivoice,
            "omnivoice.models": fake_models,
            "omnivoice.models.omnivoice_flashinfer": fake_flashinfer,
        }
        with (
            patch.dict(sys.modules, modules),
            patch.object(worker, "_progress"),
            self.assertRaisesRegex(RuntimeError, "setup failed"),
        ):
            worker._load_model(
                "request-1",
                {
                    "model_id": "fake/model",
                    "device": "cuda",
                    "enable_flashinfer": True,
                },
            )

        self.assertIsNone(worker._model)
        self.assertIsNone(worker._model_identity)

    def test_lora_output_must_be_a_directory_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_file = root / "model.bin"
            output_file.write_bytes(b"model")
            with self.assertRaises(NotADirectoryError):
                worker._validate_empty_output_dir(output_file)

            output_dir = root / "merged"
            output_dir.mkdir()
            (output_dir / "partial.bin").write_bytes(b"partial")
            with self.assertRaises(FileExistsError):
                worker._validate_empty_output_dir(output_dir)


if __name__ == "__main__":
    unittest.main()
