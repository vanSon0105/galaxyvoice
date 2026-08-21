from __future__ import annotations

import re
import unittest
from pathlib import Path

from app.common.palette import PALETTE


TOKEN_NAMES = {
    "background": "bg",
    "chrome": "chrome",
    "surface": "surface",
    "surface_raised": "surface-raised",
    "input": "input",
    "border": "border",
    "border_strong": "border-strong",
    "text": "fg",
    "text_muted": "fg-muted",
    "text_subtle": "fg-subtle",
    "accent": "accent",
    "accent_hover": "accent-hover",
    "accent_pressed": "accent-pressed",
    "accent_text": "fg-inverse",
    "accent_surface": "accent-surface",
    "accent_surface_hover": "accent-surface-hover",
    "selection": "selection",
    "success": "success",
    "warning": "warning",
    "danger": "danger",
    "preview": "preview",
}


def _css_tokens() -> dict[str, str]:
    token_path = Path(__file__).resolve().parents[2] / "frontend" / "src" / "styles" / "tokens.css"
    text = token_path.read_text(encoding="utf-8")
    return dict(re.findall(r"--color-([\w-]+):\s*(#[0-9a-fA-F]{6});", text))


class PaletteTests(unittest.TestCase):
    def test_palette_matches_frontend_color_tokens(self) -> None:
        css = _css_tokens()

        for field_name, token_name in TOKEN_NAMES.items():
            self.assertEqual(
                getattr(PALETTE, field_name).lower(),
                css[token_name].lower(),
                f"AppPalette.{field_name} must match --color-{token_name}",
            )

    def test_text_colors_have_accessible_contrast(self) -> None:
        self.assertGreaterEqual(_contrast(PALETTE.text, PALETTE.background), 7.0)
        self.assertGreaterEqual(_contrast(PALETTE.text_muted, PALETTE.surface), 4.5)
        self.assertGreaterEqual(_contrast(PALETTE.text_subtle, PALETTE.surface), 3.0)


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


if __name__ == "__main__":
    unittest.main()
