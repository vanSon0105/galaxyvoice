from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.common.diagnostics import (  # noqa: E402
    LOGGER_NAME,
    configure_logging,
    get_logger,
    log_operation_failure,
    redacted_binary_log,
    redact_sensitive_text,
)


class DiagnosticsTests(unittest.TestCase):
    def test_retained_subprocess_log_is_sanitized_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "install.log"
            with self.assertRaisesRegex(RuntimeError, "failed"):
                with redacted_binary_log(log_path) as stream:
                    stream.write(b"download https://example.invalid/?token=hf_abcdefghijk\n")
                    raise RuntimeError("failed")

            contents = log_path.read_text(encoding="utf-8")
            self.assertNotIn("hf_abcdefghijk", contents)
            self.assertIn("***", contents)

    def test_redactor_masks_provider_tokens_and_natural_key_messages(self) -> None:
        text = redact_sensitive_text(
            "Incorrect API key provided: sk-proj-123456789; "
            "NVIDIA api key: nvapi-abcdefghijk and token hf_abcdefghijk"
        )

        self.assertNotIn("sk-proj", text)
        self.assertNotIn("nvapi-", text)
        self.assertNotIn("hf_", text)
        self.assertGreaterEqual(text.count("***"), 3)

    def test_failure_log_records_operation_without_exception_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "galaxy.log"
            configure_logging(log_path)
            log_operation_failure(
                get_logger("test"),
                "Translation",
                RuntimeError("secret-key and private subtitle text"),
            )
            root_logger = logging.getLogger(LOGGER_NAME)
            for handler in root_logger.handlers:
                handler.flush()

            contents = log_path.read_text(encoding="utf-8")
            self.assertIn("ERROR galaxy_ai_studio.test Translation failed (RuntimeError)", contents)
            self.assertNotIn("secret-key", contents)
            self.assertNotIn("private subtitle text", contents)

            for handler in tuple(root_logger.handlers):
                handler_path = getattr(handler, "baseFilename", None)
                if handler_path is None or Path(handler_path) != log_path.resolve():
                    continue
                root_logger.removeHandler(handler)
                handler.close()


if __name__ == "__main__":
    unittest.main()
