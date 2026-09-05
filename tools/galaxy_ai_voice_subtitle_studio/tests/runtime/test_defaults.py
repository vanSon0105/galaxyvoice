from __future__ import annotations

import os
import unittest
from unittest import mock

from app.runtime.capabilities import PreflightRequest
from app.runtime.defaults import _audio_separation_preflight, _diarization_preflight


class DefaultPreflightTests(unittest.TestCase):
    def test_audio_separation_auto_reports_resolved_cpu(self) -> None:
        with mock.patch(
            "app.audio_separation.service.resolve_audio_device", return_value="cpu"
        ), mock.patch(
            "app.audio_separation.service.audio_separator_runtime_ready",
            return_value=(True, "ready"),
        ):
            result = _audio_separation_preflight(
                PreflightRequest("audio.separation", device="auto", options={"method": "mdx"})
            )

        self.assertTrue(result.ready)
        self.assertEqual(result.resolved_device, "cpu")

    def test_audio_separation_auto_falls_back_when_gpu_runtime_is_unavailable(self) -> None:
        with mock.patch(
            "app.audio_separation.service.resolve_audio_device", return_value="cuda"
        ), mock.patch(
            "app.audio_separation.service.audio_separator_runtime_ready",
            side_effect=[(False, "CUDA runtime missing"), (True, "CPU ready")],
        ):
            result = _audio_separation_preflight(
                PreflightRequest("audio.separation", device="auto", options={"method": "mdx"})
            )

        self.assertTrue(result.ready)
        self.assertEqual(result.resolved_device, "cpu")
        self.assertIn("Falling back", result.message)

    def test_diarization_auto_falls_back_to_cpu(self) -> None:
        with mock.patch("app.runtime.defaults.importlib.util.find_spec", return_value=object()), mock.patch(
            "app.runtime.defaults._available_diarization_devices", return_value=("cpu",)
        ), mock.patch.dict(os.environ, {"GALAXY_HF_TOKEN": "hf_test"}, clear=False):
            result = _diarization_preflight(
                PreflightRequest("diarization.pyannote", device="auto")
            )

        self.assertTrue(result.ready)
        self.assertEqual(result.resolved_device, "cpu")


if __name__ == "__main__":
    unittest.main()
