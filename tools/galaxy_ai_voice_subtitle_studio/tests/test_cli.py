from __future__ import annotations

import unittest
from unittest.mock import patch

from app.cli import main


class DesktopEntrypointTests(unittest.TestCase):
    def test_no_arguments_launches_the_web_shell(self) -> None:
        with patch("app.server.shell.run_web_app", return_value=0) as run_web_app:
            result = main([])

        self.assertEqual(result, 0)
        run_web_app.assert_called_once_with(port=3902, dev_url=None, debug=False)

    def test_explicit_web_flag_remains_backward_compatible(self) -> None:
        with patch("app.server.shell.run_web_app", return_value=0) as run_web_app:
            result = main(["--web"])

        self.assertEqual(result, 0)
        run_web_app.assert_called_once_with(port=3902, dev_url=None, debug=False)

    def test_web_flag_does_not_override_a_cli_task(self) -> None:
        voice = type("Voice", (), {"label": "Test voice"})()
        tts = type("Tts", (), {"list_voices": lambda self: [voice]})()
        with (
            patch("app.server.shell.run_web_app") as run_web_app,
            patch("app.cli.create_tts_engine", return_value=tts),
        ):
            result = main(["--web", "--list-voices"])

        self.assertEqual(result, 0)
        run_web_app.assert_not_called()


if __name__ == "__main__":
    unittest.main()
