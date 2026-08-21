from __future__ import annotations

import unittest
from pathlib import Path


class WindowsLauncherTests(unittest.TestCase):
    def test_launcher_bootstraps_the_supported_web_runtime(self) -> None:
        tool_root = Path(__file__).resolve().parents[1]
        launcher = (tool_root / "Galaxy Studio.bat").read_text(encoding="utf-8")

        self.assertIn("requirements-web.txt", launcher)
        self.assertIn("(0, 115) <= release('fastapi') < (1,)", launcher)
        self.assertIn("(0, 30) <= release('uvicorn') < (1,)", launcher)
        self.assertIn("(6,) <= release('pywebview') < (7,)", launcher)
        self.assertIn("%GALAXY_PYTHON% run.py", launcher)


if __name__ == "__main__":
    unittest.main()
