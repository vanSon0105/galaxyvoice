from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.compute import (  # noqa: E402
    AUTO_DEVICE,
    CPU_DEVICE,
    CUDA_DEVICE,
    processing_device_code,
    processing_device_label,
    resolve_torch_device,
    resolve_whisper_runtime,
)


class ComputeTests(unittest.TestCase):
    def test_device_labels_round_trip(self) -> None:
        for code in (AUTO_DEVICE, CPU_DEVICE, CUDA_DEVICE):
            self.assertEqual(
                processing_device_code(processing_device_label(code)),
                code,
            )

    def test_cpu_selection_ignores_available_cuda(self) -> None:
        self.assertEqual(
            resolve_whisper_runtime(CPU_DEVICE, cuda_device_count=1),
            ("cpu", "int8"),
        )

    def test_auto_selection_uses_cuda_when_available(self) -> None:
        self.assertEqual(
            resolve_whisper_runtime(AUTO_DEVICE, cuda_device_count=1),
            ("cuda", "float16"),
        )

    def test_explicit_cuda_selection_fails_when_no_gpu_exists(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "NVIDIA GPU"):
            resolve_whisper_runtime(CUDA_DEVICE, cuda_device_count=0)

    def test_torch_auto_selection_uses_cpu_without_nvidia_hardware(self) -> None:
        self.assertEqual(
            resolve_torch_device(AUTO_DEVICE, nvidia_available=False),
            CPU_DEVICE,
        )

    def test_torch_explicit_cuda_requires_nvidia_hardware(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "NVIDIA GPU"):
            resolve_torch_device(CUDA_DEVICE, nvidia_available=False)


if __name__ == "__main__":
    unittest.main()
