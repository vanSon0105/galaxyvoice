from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.common.env_config import first_env  # noqa: E402


class EnvConfigTests(unittest.TestCase):
    def test_first_env_prefers_process_environment(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "process-key"}, clear=True):
            with patch("app.common.env_config._read_windows_environment", return_value="user-key"):
                self.assertEqual(first_env("OPENAI_API_KEY"), "process-key")

    def test_first_env_falls_back_to_windows_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("app.common.env_config._read_windows_environment", return_value="user-key"):
                self.assertEqual(first_env("OPENAI_API_KEY"), "user-key")

    def test_first_env_uses_default_when_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("app.common.env_config._read_windows_environment", return_value=""):
                self.assertEqual(first_env("OPENAI_API_KEY", default="fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()
