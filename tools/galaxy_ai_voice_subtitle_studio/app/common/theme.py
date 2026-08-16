from __future__ import annotations

import ctypes
import os
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from tkinter import ttk


@dataclass(frozen=True)
class AppPalette:
    background: str = "#111315"
    surface: str = "#191c1f"
    surface_raised: str = "#23272b"
    input: str = "#15181b"
    border: str = "#383d43"
    border_strong: str = "#555c64"
    text: str = "#f4f1ea"
    text_muted: str = "#c3c0b9"
    text_subtle: str = "#959ba2"
    accent: str = "#d08ca1"
    accent_hover: str = "#e09bb0"
    accent_pressed: str = "#b9758a"
    accent_text: str = "#171214"
    selection: str = "#70495a"
    success: str = "#78b9a8"
    warning: str = "#e0ad67"
    danger: str = "#dc766f"
    preview: str = "#0c0f11"


PALETTE = AppPalette()
BODY_FONT_SIZE = 11
SMALL_FONT_SIZE = 10
HEADING_FONT_SIZE = 18
MONO_FONT_SIZE = 10
BASE_DPI = 96.0


def enable_windows_dpi_awareness() -> None:
    """Enable crisp Tk rendering before the first root window is created."""
    if os.name != "nt":
        return

    try:
        set_context = ctypes.windll.user32.SetProcessDpiAwarenessContext
        if set_context(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def _first_installed_font(root: tk.Misc, candidates: tuple[str, ...]) -> str:
    installed = {family.casefold(): family for family in tkfont.families(root)}
    for candidate in candidates:
        match = installed.get(candidate.casefold())
        if match:
            return match
    return candidates[-1]


def display_scale(root: tk.Misc) -> float:
    try:
        return max(1.0, min(2.5, float(root.winfo_fpixels("1i")) / BASE_DPI))
    except (tk.TclError, TypeError, ValueError):
        return 1.0


def scaled_pixels(root: tk.Misc, value: int | float) -> int:
    return max(1, round(float(value) * display_scale(root)))


def configure_main_window(
    root: tk.Tk,
    *,
    width: int,
    height: int,
    min_width: int,
    min_height: int,
) -> float:
    scale = display_scale(root)
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    target_width = min(round(width * scale), screen_width)
    target_height = min(round(height * scale), screen_height)
    root.geometry(f"{target_width}x{target_height}")
    root.minsize(
        min(round(min_width * scale), screen_width),
        min(round(min_height * scale), screen_height),
    )
    return scale


def _configure_named_fonts(root: tk.Misc) -> tuple[str, str]:
    body_family = _first_installed_font(
        root,
        ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI"),
    )
    mono_family = _first_installed_font(
        root,
        ("Cascadia Mono", "Cascadia Code", "Consolas"),
    )

    named_fonts = {
        "TkDefaultFont": (body_family, BODY_FONT_SIZE, "normal"),
        "TkTextFont": (body_family, BODY_FONT_SIZE, "normal"),
        "TkMenuFont": (body_family, BODY_FONT_SIZE, "normal"),
        "TkHeadingFont": (body_family, BODY_FONT_SIZE, "bold"),
        "TkCaptionFont": (body_family, SMALL_FONT_SIZE, "normal"),
        "TkSmallCaptionFont": (body_family, SMALL_FONT_SIZE, "normal"),
        "TkFixedFont": (mono_family, MONO_FONT_SIZE, "normal"),
        "TkTooltipFont": (body_family, SMALL_FONT_SIZE, "normal"),
    }
    for name, (family, size, weight) in named_fonts.items():
        try:
            tkfont.nametofont(name, root=root).configure(
                family=family,
                size=size,
                weight=weight,
            )
        except tk.TclError:
            continue
    return body_family, mono_family


def _configure_tk_widgets(root: tk.Misc) -> None:
    palette = PALETTE
    root.tk_setPalette(
        background=palette.background,
        foreground=palette.text,
        activeBackground=palette.surface_raised,
        activeForeground=palette.text,
        highlightColor=palette.accent,
        highlightBackground=palette.border,
        selectBackground=palette.selection,
        selectForeground=palette.text,
        disabledForeground=palette.text_subtle,
    )

    options = {
        "*Font": "TkDefaultFont",
        "*Text.Font": "TkTextFont",
        "*Text.background": palette.input,
        "*Text.foreground": palette.text,
        "*Text.insertBackground": palette.text,
        "*Text.selectBackground": palette.selection,
        "*Text.selectForeground": palette.text,
        "*Text.highlightBackground": palette.border,
        "*Text.highlightColor": palette.accent,
        "*Text.relief": "flat",
        "*Listbox.background": palette.input,
        "*Listbox.foreground": palette.text,
        "*Listbox.selectBackground": palette.selection,
        "*Listbox.selectForeground": palette.text,
        "*Menu.background": palette.surface_raised,
        "*Menu.foreground": palette.text,
        "*Menu.activeBackground": palette.selection,
        "*Menu.activeForeground": palette.text,
        "*Menu.relief": "flat",
        "*TCombobox*Listbox.background": palette.surface_raised,
        "*TCombobox*Listbox.foreground": palette.text,
        "*TCombobox*Listbox.selectBackground": palette.selection,
        "*TCombobox*Listbox.selectForeground": palette.text,
    }
    for pattern, value in options.items():
        root.option_add(pattern, value, "interactive")


def _enable_windows_dark_title_bar(root: tk.Tk) -> None:
    if os.name != "nt":
        return
    try:
        root.update_idletasks()
        window_id = root.winfo_id()
        get_parent = ctypes.windll.user32.GetParent
        get_parent.argtypes = [ctypes.c_void_p]
        get_parent.restype = ctypes.c_void_p
        hwnd = get_parent(ctypes.c_void_p(window_id)) or window_id
        enabled = ctypes.c_int(1)
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        set_attribute.restype = ctypes.c_long
        for attribute in (20, 19):
            result = set_attribute(
                ctypes.c_void_p(hwnd),
                attribute,
                ctypes.byref(enabled),
                ctypes.sizeof(enabled),
            )
            if result == 0:
                break
    except (AttributeError, OSError, tk.TclError):
        pass


def apply_app_theme(root: tk.Tk) -> ttk.Style:
    palette = PALETTE
    scale = display_scale(root)

    def metric(value: int | float) -> int:
        return max(1, round(float(value) * scale))

    body_family, mono_family = _configure_named_fonts(root)
    _configure_tk_widgets(root)
    root.configure(background=palette.background)
    _enable_windows_dark_title_bar(root)

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    body_font = (body_family, BODY_FONT_SIZE)
    small_font = (body_family, SMALL_FONT_SIZE)
    medium_font = (body_family, BODY_FONT_SIZE, "bold")
    heading_font = (body_family, HEADING_FONT_SIZE, "bold")
    mono_font = (mono_family, MONO_FONT_SIZE)

    style.configure(
        ".",
        background=palette.background,
        foreground=palette.text,
        font=body_font,
        bordercolor=palette.border,
        darkcolor=palette.border,
        lightcolor=palette.border,
        focuscolor=palette.accent,
        troughcolor=palette.input,
    )
    style.configure("TFrame", background=palette.background)
    style.configure("Header.TFrame", background=palette.background)
    style.configure("Toolbar.TFrame", background=palette.surface)
    style.configure(
        "Panel.TFrame",
        background=palette.surface,
        bordercolor=palette.border,
        borderwidth=1,
        relief="solid",
    )
    style.configure("Surface.TFrame", background=palette.surface)

    style.configure("TLabel", background=palette.background, foreground=palette.text)
    style.configure("Panel.TLabel", background=palette.surface, foreground=palette.text)
    style.configure("Toolbar.TLabel", background=palette.surface, foreground=palette.text)
    style.configure(
        "Muted.TLabel",
        background=palette.background,
        foreground=palette.text_muted,
        font=small_font,
    )
    style.configure(
        "Status.TLabel",
        background=palette.surface_raised,
        foreground=palette.text_muted,
        font=small_font,
        padding=(9, 4),
    )
    style.configure(
        "Header.TLabel",
        background=palette.background,
        foreground=palette.text,
        font=heading_font,
    )
    style.configure(
        "Section.TLabel",
        background=palette.surface,
        foreground=palette.text,
        font=medium_font,
    )
    style.configure(
        "PageSection.TLabel",
        background=palette.background,
        foreground=palette.text,
        font=medium_font,
    )

    style.configure("TNotebook", background=palette.background, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure(
        "TNotebook.Tab",
        background=palette.background,
        foreground=palette.text_muted,
        font=body_font,
        padding=(14, 7),
        borderwidth=0,
        focuscolor=palette.background,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", palette.surface), ("active", palette.surface_raised)],
        foreground=[("selected", palette.text), ("active", palette.text)],
        bordercolor=[("selected", palette.accent), ("active", palette.border_strong)],
    )

    style.configure(
        "TButton",
        background=palette.surface_raised,
        foreground=palette.text,
        bordercolor=palette.border,
        borderwidth=1,
        focusthickness=1,
        focuscolor=palette.accent,
        padding=(11, 7),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[
            ("pressed", palette.selection),
            ("active", palette.border),
            ("disabled", palette.surface),
        ],
        foreground=[("disabled", palette.text_subtle)],
        bordercolor=[("focus", palette.accent), ("active", palette.border_strong)],
    )
    style.configure(
        "Accent.TButton",
        background=palette.accent,
        foreground=palette.accent_text,
        bordercolor=palette.accent,
        font=medium_font,
    )
    style.map(
        "Accent.TButton",
        background=[
            ("pressed", palette.accent_pressed),
            ("active", palette.accent_hover),
            ("disabled", palette.surface_raised),
        ],
        foreground=[("disabled", palette.text_subtle)],
        bordercolor=[("focus", palette.text), ("disabled", palette.border)],
    )

    for widget_style in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(
            widget_style,
            fieldbackground=palette.input,
            background=palette.input,
            foreground=palette.text,
            bordercolor=palette.border,
            insertcolor=palette.text,
            arrowcolor=palette.text_muted,
            padding=(7, 6),
        )
        style.map(
            widget_style,
            fieldbackground=[
                ("readonly", palette.input),
                ("disabled", palette.surface),
                ("focus", palette.input),
            ],
            foreground=[
                ("readonly", palette.text),
                ("disabled", palette.text_subtle),
            ],
            bordercolor=[("focus", palette.accent), ("active", palette.border_strong)],
            arrowcolor=[("disabled", palette.text_subtle), ("active", palette.text)],
            selectbackground=[("readonly", palette.selection)],
            selectforeground=[("readonly", palette.text)],
        )

    for widget_style in ("TCheckbutton", "TRadiobutton"):
        style.configure(
            widget_style,
            background=palette.surface,
            foreground=palette.text,
            indicatorbackground=palette.input,
            indicatorforeground=palette.accent_text,
            indicatorcolor=palette.accent,
            indicatorsize=metric(14),
            indicatormargin=metric(3),
            padding=(2, 3),
        )
        style.map(
            widget_style,
            background=[("active", palette.surface)],
            foreground=[("disabled", palette.text_subtle)],
            indicatorbackground=[
                ("selected", palette.accent),
                ("disabled", palette.surface_raised),
            ],
            indicatorcolor=[("selected", palette.accent)],
        )

    style.configure(
        "TLabelframe",
        background=palette.surface,
        bordercolor=palette.border,
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "TLabelframe.Label",
        background=palette.surface,
        foreground=palette.text,
        font=medium_font,
    )
    style.configure(
        "Treeview",
        background=palette.input,
        fieldbackground=palette.input,
        foreground=palette.text,
        bordercolor=palette.border,
        rowheight=metric(30),
        font=body_font,
    )
    style.map(
        "Treeview",
        background=[("selected", palette.selection)],
        foreground=[("selected", palette.text)],
    )
    style.configure(
        "Treeview.Heading",
        background=palette.surface_raised,
        foreground=palette.text_muted,
        bordercolor=palette.border,
        font=medium_font,
        padding=(7, 7),
        relief="flat",
    )
    style.map(
        "Treeview.Heading",
        background=[("active", palette.border)],
        foreground=[("active", palette.text)],
    )

    style.configure(
        "TScale",
        background=palette.surface,
        troughcolor=palette.input,
        bordercolor=palette.border,
        lightcolor=palette.accent,
        darkcolor=palette.accent,
        sliderlength=metric(18),
        sliderthickness=metric(18),
    )
    style.configure(
        "TProgressbar",
        background=palette.accent,
        troughcolor=palette.input,
        bordercolor=palette.border,
        lightcolor=palette.accent,
        darkcolor=palette.accent,
        thickness=metric(8),
    )
    style.configure(
        "TScrollbar",
        background=palette.surface_raised,
        troughcolor=palette.input,
        bordercolor=palette.input,
        arrowcolor=palette.text_muted,
        arrowsize=metric(13),
        width=metric(14),
        relief="flat",
    )
    style.map(
        "TScrollbar",
        background=[("active", palette.border_strong), ("pressed", palette.accent)],
        arrowcolor=[("active", palette.text)],
    )
    style.configure("TSeparator", background=palette.border)
    style.configure("TPanedwindow", background=palette.background)
    style.configure("Sash", sashthickness=6, background=palette.border)
    style.configure("Mono.TLabel", font=mono_font)
    return style


def text_widget_options(*, log: bool = False) -> dict[str, object]:
    palette = PALETTE
    return {
        "bg": palette.preview if log else palette.input,
        "fg": palette.text if not log else "#e6e9e7",
        "insertbackground": palette.text,
        "selectbackground": palette.selection,
        "selectforeground": palette.text,
        "highlightbackground": palette.border,
        "highlightcolor": palette.accent,
        "highlightthickness": 1,
        "relief": "flat",
    }
