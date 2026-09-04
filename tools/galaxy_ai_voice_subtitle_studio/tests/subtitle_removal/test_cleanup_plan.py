from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.subtitle_removal.plan import (  # noqa: E402
    RemovalMask,
    mask_union_region,
    quality_warnings,
    validate_masks,
)


class CleanupPlanTests(unittest.TestCase):
    def test_validates_named_masks_and_time_ranges(self) -> None:
        masks = (
            RemovalMask("lower", "Lower captions", (5, 72, 90, 20), 0.0, 8.5),
            RemovalMask("top", "Top captions", (10, 4, 80, 18), 8.5, None),
        )

        self.assertEqual(validate_masks(masks, duration_seconds=30), masks)
        self.assertEqual(mask_union_region(masks), (5, 4, 90, 88))

    def test_rejects_empty_names_and_invalid_ranges(self) -> None:
        with self.assertRaisesRegex(ValueError, "name"):
            validate_masks((RemovalMask("mask-1", "", (5, 75, 90, 20)),), 30)
        with self.assertRaisesRegex(ValueError, "end"):
            validate_masks((RemovalMask("mask-1", "Captions", (5, 75, 90, 20), 4, 4),), 30)
        with self.assertRaisesRegex(ValueError, "duration"):
            validate_masks((RemovalMask("mask-1", "Captions", (5, 75, 90, 20), 0, 31),), 30)

    def test_quality_warnings_are_explicit_for_risky_cleanup(self) -> None:
        masks = (
            RemovalMask("one", "Large", (0, 40, 100, 50), 0, 10),
            RemovalMask("two", "Overlap", (10, 60, 80, 30), 5, 15),
        )

        warnings = quality_warnings("blur", masks, processing_device="cpu")

        self.assertTrue(any("blur" in warning.lower() for warning in warnings))
        self.assertTrue(any("large" in warning.lower() for warning in warnings))
        self.assertTrue(any("overlap" in warning.lower() for warning in warnings))


if __name__ == "__main__":
    unittest.main()
