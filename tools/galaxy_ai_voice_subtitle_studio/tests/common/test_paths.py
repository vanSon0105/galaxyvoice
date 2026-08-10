from __future__ import annotations

import unittest
from pathlib import Path

from app.common.config import default_config_path
from app.common.paths import repository_root, studio_root


class PathTests(unittest.TestCase):
    def test_shared_roots_stay_correct_after_feature_modules_are_moved(self) -> None:
        expected_studio = Path(__file__).resolve().parents[2]

        self.assertEqual(studio_root(), expected_studio)
        self.assertEqual(repository_root(), expected_studio.parents[1])
        self.assertEqual(default_config_path(), expected_studio / "config.json")


if __name__ == "__main__":
    unittest.main()
