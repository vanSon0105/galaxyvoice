from __future__ import annotations

import ast
import unittest
from pathlib import Path


class TkinterRemovalTests(unittest.TestCase):
    def test_app_has_no_tkinter_imports(self) -> None:
        app_root = Path(__file__).resolve().parents[2] / "app"
        offenders: list[str] = []

        for path in app_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported_names: list[str] = []
                if isinstance(node, ast.Import):
                    imported_names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_names = [node.module]
                if any(name == "tkinter" or name.startswith("tkinter.") for name in imported_names):
                    offenders.append(str(path.relative_to(app_root)))

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
