from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
