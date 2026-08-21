from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.common.env_config import first_env, set_user_environment  # noqa: E402


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

    def test_set_user_environment_writes_registry_and_current_process(self) -> None:
        fake_key = MagicMock()
        fake_winreg = MagicMock()
        fake_winreg.HKEY_CURRENT_USER = object()
        fake_winreg.REG_SZ = 1
        fake_winreg.CreateKey.return_value.__enter__.return_value = fake_key

        with patch.dict(os.environ, {}, clear=True):
            with patch.dict(sys.modules, {"winreg": fake_winreg}):
                with patch("app.common.env_config.sys.platform", "win32"):
                    with patch("app.common.env_config._broadcast_environment_change"):
                        set_user_environment("GALAXY_DEEPSEEK_API_KEY", "secret-value")
                        self.assertEqual(os.environ["GALAXY_DEEPSEEK_API_KEY"], "secret-value")

        fake_winreg.SetValueEx.assert_called_once_with(
            fake_key,
            "GALAXY_DEEPSEEK_API_KEY",
            0,
            fake_winreg.REG_SZ,
            "secret-value",
        )

    def test_set_user_environment_rejects_invalid_name(self) -> None:
        with self.assertRaises(ValueError):
            set_user_environment("BAD NAME", "secret-value")


if __name__ == "__main__":
    unittest.main()
