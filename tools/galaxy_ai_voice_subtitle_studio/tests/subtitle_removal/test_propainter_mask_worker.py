from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.propainter_mask_worker import _validate_frame_count  # noqa: E402


class ProPainterMaskWorkerTests(unittest.TestCase):
    def test_partial_video_decode_is_rejected_before_propainter_runs(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "47/48"):
            _validate_frame_count(47, 48)

    def test_unknown_container_frame_count_does_not_reject_decoded_masks(self) -> None:
        _validate_frame_count(48, 0)


if __name__ == "__main__":
    unittest.main()
