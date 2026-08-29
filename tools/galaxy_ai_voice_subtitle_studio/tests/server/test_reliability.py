from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.server.main import create_app


class ReliabilityApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="galaxy_reliability_")
        self.client = TestClient(create_app(config_path=Path(self._temp.name) / "config.json"))

    def tearDown(self) -> None:
        self.client.close()
        self._temp.cleanup()

    def test_report_returns_lightweight_system_information(self) -> None:
        with mock.patch(
            "app.reliability.service.detect_nvidia_hardware", return_value=False
        ), mock.patch("app.reliability.service.detect_cuda_device_count", return_value=0):
            response = self.client.get("/api/reliability/report")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommended_device"], "cpu")
        self.assertGreaterEqual(response.json()["cpu_count"], 1)

    def test_audit_rejects_unknown_capability(self) -> None:
        response = self.client.post(
            "/api/reliability/audit",
            json={"capability_id": "missing.capability"},
        )
        self.assertEqual(response.status_code, 404)

    def test_logs_endpoint_never_returns_more_than_requested(self) -> None:
        with mock.patch(
            "app.server.routers.reliability.read_diagnostic_log",
            return_value=["line"],
        ):
            response = self.client.get("/api/reliability/logs?limit=5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lines"], ["line"])


if __name__ == "__main__":
    unittest.main()
