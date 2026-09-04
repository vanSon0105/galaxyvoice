from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.omnivoice.workspaces.dubbing.ingest import (
    DubbingIngestService,
    build_download_command,
    validate_remote_media_url,
)


class DubbingIngestServiceTests(unittest.TestCase):
    def test_local_video_uses_matching_sidecar_caption(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "lesson.mp4"
            video.write_bytes(b"video")
            sidecar = root / "lesson.vi.srt"
            sidecar.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nXin chao\n",
                encoding="utf-8",
            )

            result = DubbingIngestService().ingest_local(video, source_language="vi")

        self.assertEqual(result.source_kind, "video")
        self.assertEqual(result.source_path, str(video.resolve()))
        self.assertEqual(result.selected_caption.language, "vi")
        self.assertIn("Xin chao", result.selected_caption.text)

    def test_local_ingest_rejects_unsupported_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "notes.txt"
            path.write_text("not media", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "định dạng"):
                DubbingIngestService().ingest_local(path)

    def test_local_generic_sidecar_is_used_when_language_is_not_in_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "lesson.mp4"
            video.write_bytes(b"video")
            (root / "lesson.srt").write_text("generic caption", encoding="utf-8")

            result = DubbingIngestService().ingest_local(video, source_language="vi")

        self.assertEqual(result.selected_caption.language, "und")
        self.assertEqual(result.selected_caption.text, "generic caption")

    def test_url_validation_rejects_credentials_and_private_addresses(self) -> None:
        with self.assertRaisesRegex(ValueError, "thông tin đăng nhập"):
            validate_remote_media_url("https://name:secret@example.com/video")
        with self.assertRaisesRegex(ValueError, "mạng nội bộ"):
            validate_remote_media_url("http://127.0.0.1/video")

    def test_download_command_is_single_item_and_keeps_cookie_transient(self) -> None:
        command = build_download_command(
            ("yt-dlp",),
            "https://www.youtube.com/watch?v=abc",
            Path("D:/output"),
            pull_captions=True,
            source_language="en",
            target_language="vi",
            cookie_path=Path("D:/private/cookies.txt"),
        )

        self.assertIn("--no-playlist", command)
        self.assertEqual(command[command.index("--max-downloads") + 1], "1")
        self.assertIn("--write-auto-subs", command)
        self.assertEqual(command[command.index("--cookies") + 1], "D:\\private\\cookies.txt")

    def test_url_ingest_selects_source_and_translation_captions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cookie = root / "cookies.txt"
            cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

            def runner(command, output_dir, **_kwargs):
                self.assertIn("--cookies", command)
                (output_dir / "clip.webm").write_bytes(b"media")
                (output_dir / "clip.en.srt").write_text("source", encoding="utf-8")
                (output_dir / "clip.vi.srt").write_text("translated", encoding="utf-8")

            service = DubbingIngestService(
                downloader_command=("yt-dlp",),
                host_resolver=lambda _host: ("8.8.8.8",),
                downloader_runner=runner,
            )
            result = service.ingest_url(
                "https://video.example/watch/1",
                root / "downloads",
                pull_captions=True,
                source_language="en",
                target_language="vi",
                cookie_path=cookie,
            )

        self.assertEqual(result.source_kind, "video")
        self.assertEqual(result.selected_caption.language, "en")
        self.assertEqual(result.translated_caption.language, "vi")
        payload = result.to_dict()
        self.assertNotIn("cookie", str(payload).casefold())


if __name__ == "__main__":
    unittest.main()
