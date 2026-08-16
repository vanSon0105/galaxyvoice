from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.common.theme import (  # noqa: E402
    BODY_FONT_SIZE,
    PALETTE,
    apply_app_theme,
    display_scale,
    scaled_pixels,
    text_widget_options,
)
from app.voicestudio.gui import VOICESTUDIO_THEME_SCRIPT  # noqa: E402


def _channel(value: int) -> float:
    normalized = value / 255
    if normalized <= 0.04045:
        return normalized / 12.92
    return ((normalized + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def _contrast(first: str, second: str) -> float:
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class ThemeTests(unittest.TestCase):
    def test_text_colors_have_accessible_contrast(self) -> None:
        self.assertGreaterEqual(_contrast(PALETTE.text, PALETTE.background), 7.0)
        self.assertGreaterEqual(_contrast(PALETTE.text_muted, PALETTE.surface), 4.5)
        self.assertGreaterEqual(_contrast(PALETTE.text_subtle, PALETTE.surface), 3.0)

    def test_tk_theme_configures_fonts_and_interactive_controls(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            root.withdraw()
            style = apply_app_theme(root)

            self.assertEqual(root.cget("background"), PALETTE.background)
            self.assertEqual(style.lookup("TEntry", "fieldbackground"), PALETTE.input)
            self.assertEqual(style.lookup("Treeview", "background"), PALETTE.input)
            self.assertGreaterEqual(int(style.lookup("Treeview", "rowheight")), 30)
            self.assertGreaterEqual(tkfont.nametofont("TkDefaultFont", root=root).cget("size"), BODY_FONT_SIZE)
            self.assertGreaterEqual(scaled_pixels(root, 20), 20)
            self.assertGreaterEqual(display_scale(root), 1.0)
        finally:
            root.destroy()

    def test_text_widget_options_match_the_shared_palette(self) -> None:
        editor = text_widget_options()
        log = text_widget_options(log=True)

        self.assertEqual(editor["bg"], PALETTE.input)
        self.assertEqual(editor["fg"], PALETTE.text)
        self.assertEqual(log["bg"], PALETTE.preview)
        self.assertEqual(editor["selectbackground"], PALETTE.selection)

    def test_voicestudio_override_increases_readability(self) -> None:
        self.assertIn('"--color-fg": "#f4f1ea"', VOICESTUDIO_THEME_SCRIPT)
        self.assertIn('"--text-base": "0.84rem"', VOICESTUDIO_THEME_SCRIPT)
        self.assertIn("webkitFontSmoothing", VOICESTUDIO_THEME_SCRIPT)
        self.assertIn("galaxy-visual-theme", VOICESTUDIO_THEME_SCRIPT)


if __name__ == "__main__":
    unittest.main()
