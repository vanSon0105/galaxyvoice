from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ffmpeg import find_ffmpeg, find_ffprobe  # noqa: E402


class FfmpegTests(unittest.TestCase):
    def test_find_ffmpeg_prefers_bundled_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundled = root / "bin" / "ffmpeg.exe"
            bundled.parent.mkdir()
            bundled.write_bytes(b"fake")

            self.assertEqual(find_ffmpeg(root), str(bundled))

    def test_find_ffprobe_prefers_bundled_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundled = root / "bin" / "ffprobe.exe"
            bundled.parent.mkdir()
            bundled.write_bytes(b"fake")

            self.assertEqual(find_ffprobe(root), str(bundled))


if __name__ == "__main__":
    unittest.main()
