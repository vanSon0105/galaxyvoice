from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.omnivoice.runtime import OmniVoiceRuntime
from app.omnivoice import worker_pool


class OmniVoiceWorkerPoolTests(unittest.TestCase):
    def tearDown(self) -> None:
        worker_pool.shutdown_shared_worker_client()

    def test_reuses_one_client_and_closes_it_on_shutdown(self) -> None:
        runtime = Mock(spec=OmniVoiceRuntime)
        client = Mock()
        with patch.object(worker_pool, "OmniVoiceWorkerClient", return_value=client) as factory:
            first = worker_pool.get_shared_worker_client(runtime, Path("worker.py"))
            second = worker_pool.get_shared_worker_client(runtime, Path("worker.py"))

        self.assertIs(first, client)
        self.assertIs(second, client)
        factory.assert_called_once_with(runtime, Path("worker.py"))

        worker_pool.shutdown_shared_worker_client()
        client.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
