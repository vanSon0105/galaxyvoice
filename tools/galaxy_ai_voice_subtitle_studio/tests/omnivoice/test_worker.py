from __future__ import annotations

import io
import json
import unittest
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


if __name__ == "__main__":
    unittest.main()
