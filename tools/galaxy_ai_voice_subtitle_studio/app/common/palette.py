from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppPalette:
    """Color contract shared by backend checks and the React token sheet."""

    background: str = "#111315"
    chrome: str = "#0c0f11"
    surface: str = "#15181b"
    surface_raised: str = "#191c1f"
    input: str = "#15181b"
    border: str = "#2e3033"
    border_strong: str = "#484b4e"
    text: str = "#f4f1ea"
    text_muted: str = "#c3c0b9"
    text_subtle: str = "#9da2a8"
    accent: str = "#d08ca1"
    accent_hover: str = "#e09bb0"
    accent_pressed: str = "#b9758a"
    accent_text: str = "#171214"
    accent_surface: str = "#2b1d23"
    accent_surface_hover: str = "#3a252e"
    selection: str = "#70495a"
    success: str = "#78b9a8"
    warning: str = "#e0ad67"
    danger: str = "#dc766f"
    preview: str = "#0c0f11"


PALETTE = AppPalette()
