from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.reliability.service import (
    InsufficientDiskSpaceError,
    ReliabilityService,
    estimate_audio_bytes,
    estimate_media_working_bytes,
    estimate_required_bytes,
    ensure_disk_space,
)
from app.runtime.capabilities import (
    CapabilityDescriptor,
    CapabilityRegistry,
    FunctionCapabilityAdapter,
    PreflightRequest,
    PreflightResult,
)


class ReliabilityServiceTests(unittest.TestCase):
    def test_audio_estimate_scales_with_text_and_output_count(self) -> None:
        short = estimate_audio_bytes("hello", minimum_bytes=1)
        long = estimate_audio_bytes("hello" * 1_000, output_count=2, minimum_bytes=1)
        self.assertGreater(long, short)
        self.assertEqual(short, 5 * 8_000 * 2)

    def test_output_estimate_uses_source_size_and_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.bin"
            source.write_bytes(b"x" * 100)
            self.assertEqual(
                estimate_required_bytes((source,), minimum_bytes=50, multiplier=2),
                200,
            )
            self.assertEqual(estimate_required_bytes((), minimum_bytes=50), 50)

    def test_media_estimate_accounts_for_decoded_pcm_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "app.reliability.service._probe_media_duration_seconds", return_value=60.0
        ):
            source = Path(temp_dir) / "compressed.mp3"
            source.write_bytes(b"tiny")
            required = estimate_media_working_bytes(
                (source,), sample_rate=48_000, channels=2, bytes_per_sample=4,
                working_copies=2, minimum_bytes=1, fallback_multiplier=1,
            )

        self.assertEqual(required, 60 * 3 * 48_000 * 2 * 4)

    def test_disk_guard_uses_nearest_existing_parent_and_reserve(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "new" / "project"
            usage = mock.Mock(total=10_000, used=2_000, free=8_000)
            with mock.patch("app.reliability.service.shutil.disk_usage", return_value=usage):
                check = ensure_disk_space(destination, required_bytes=2_000, reserve_bytes=1_000)

            self.assertTrue(check.ready)
            self.assertEqual(check.path, str(Path(temp_dir).resolve()))
            self.assertEqual(check.available_bytes, 8_000)

    def test_disk_guard_raises_an_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            usage = mock.Mock(total=10_000, used=9_500, free=500)
            with mock.patch("app.reliability.service.shutil.disk_usage", return_value=usage):
                with self.assertRaisesRegex(InsufficientDiskSpaceError, "dung lượng trống"):
                    ensure_disk_space(Path(temp_dir), required_bytes=1_000, reserve_bytes=100)

    def test_operation_audit_recommends_cpu_model_and_reports_fallback(self) -> None:
        registry = CapabilityRegistry()
        descriptor = CapabilityDescriptor(
            "asr.test",
            "asr",
            "Test ASR",
            "test",
            ("auto", "cuda", "cpu"),
        )
        registry.register(
            FunctionCapabilityAdapter(
                descriptor,
                lambda request: PreflightResult.ready(
                    request.capability_id,
                    requested_device=request.device,
                    resolved_device="cpu",
                    message="CPU fallback",
                ),
            )
        )
        service = ReliabilityService(registry)

        with mock.patch("app.reliability.service.detect_nvidia_hardware", return_value=False), mock.patch(
            "app.reliability.service.detect_cuda_device_count", return_value=0
        ):
            report = service.audit(
                PreflightRequest("asr.test", device="auto"),
                output_path="",
                required_disk_bytes=0,
            )

        self.assertTrue(report.ready)
        self.assertTrue(report.fallback_used)
        self.assertEqual(report.recommended_model_id, "base")
        self.assertTrue(any(check.code == "device-fallback" for check in report.checks))

    def test_operation_audit_converts_probe_failures_to_unavailable(self) -> None:
        registry = mock.Mock()
        registry.preflight.side_effect = RuntimeError(
            "runtime probe failed for sk-abcdefghijklmnopqrstuvwxyz"
        )
        registry.get.return_value = CapabilityDescriptor(
            "video.test", "video", "Test video", "test", ("auto", "cpu")
        )

        report = ReliabilityService(registry).audit(PreflightRequest("video.test"))

        self.assertFalse(report.ready)
        self.assertEqual(report.state, "unavailable")
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", report.message)
        self.assertTrue(any(check.code == "runtime-probe" for check in report.checks))

    def test_system_report_is_lightweight_and_does_not_probe_capability_runtimes(self) -> None:
        service = ReliabilityService(CapabilityRegistry())
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "app.reliability.service.detect_nvidia_hardware", return_value=True
        ), mock.patch("app.reliability.service.detect_cuda_device_count", return_value=1):
            report = service.system_report((Path(temp_dir),))

        self.assertGreaterEqual(report.cpu_count, 1)
        self.assertTrue(report.nvidia_gpu)
        self.assertEqual(report.recommended_device, "cuda")
        self.assertEqual(len(report.disks), 1)


if __name__ == "__main__":
    unittest.main()
