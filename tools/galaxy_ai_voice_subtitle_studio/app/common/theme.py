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
BODY_FONT_SIZE = 10
SMALL_FONT_SIZE = 9
HEADING_FONT_SIZE = 12
MONO_FONT_SIZE = 9
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
    try:
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
    except tk.TclError as error:
        if "invalid command name" not in str(error) or "tk_setPalette" not in str(error):
            raise

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


def _configure_notebook_tab(
    style: ttk.Style,
    root: tk.Misc,
    *,
    style_name: str,
    shelf: str,
    selected_surface: str,
    hover_surface: str,
    font: tuple[object, ...],
    padding: tuple[int, int],
    selected_foreground: str,
) -> None:
    """Style a flat notebook tab using plain colors.

    Image-based tab elements are deliberately avoided: ttk repaints
    stretchable photo elements on every redraw, which made a single tab
    switch cost multiple seconds on Windows (measured 3-11 s per switch).
    """
    palette = PALETTE
    style.configure(
        f"{style_name}.Tab",
        background=shelf,
        foreground=palette.text_muted,
        font=font,
        padding=padding,
        borderwidth=0,
        focuscolor=palette.accent,
        focusthickness=1,
    )
    style.map(
        f"{style_name}.Tab",
        background=[
            ("selected", selected_surface),
            ("active", hover_surface),
        ],
        foreground=[
            ("selected", selected_foreground),
            ("active", palette.text),
            ("disabled", palette.text_subtle),
        ],
        focuscolor=[("!focus", selected_surface)],
    )


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
    tab_font = (body_family, SMALL_FONT_SIZE)

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
    style.configure("Header.TFrame", background=palette.chrome)
    style.configure("HeaderCluster.TFrame", background=palette.chrome)
    style.configure("Toolbar.TFrame", background=palette.chrome)
    style.configure(
        "Panel.TFrame",
        background=palette.surface,
        bordercolor=palette.surface,
        borderwidth=0,
        relief="flat",
    )
    style.configure("Surface.TFrame", background=palette.surface)
    style.configure(
        "Card.TFrame",
        background=palette.surface,
        bordercolor=palette.surface,
        borderwidth=0,
        relief="flat",
    )
    style.configure("CardHeader.TFrame", background=palette.surface)
    style.configure("Inset.TFrame", background=palette.input)
    style.configure("Transport.TFrame", background=palette.surface_raised)

    style.configure("TLabel", background=palette.background, foreground=palette.text)
    style.configure(
        "Brand.TLabel",
        background=palette.chrome,
        foreground=palette.text,
        font=(body_family, HEADING_FONT_SIZE, "bold"),
    )
    style.configure(
        "BrandAccent.TLabel",
        background=palette.chrome,
        foreground=palette.accent,
        font=(body_family, HEADING_FONT_SIZE, "bold"),
    )
    style.configure(
        "StatusDot.TLabel",
        background=palette.chrome,
        foreground=palette.success,
        font=(body_family, SMALL_FONT_SIZE),
    )
    style.configure("Panel.TLabel", background=palette.surface, foreground=palette.text)
    style.configure("Toolbar.TLabel", background=palette.surface, foreground=palette.text)
    style.configure("Card.TLabel", background=palette.surface, foreground=palette.text)
    style.configure(
        "CardMuted.TLabel",
        background=palette.surface,
        foreground=palette.text_muted,
        font=small_font,
    )
    style.configure(
        "CardTitle.TLabel",
        background=palette.surface,
        foreground=palette.text,
        font=(body_family, BODY_FONT_SIZE + 1, "bold"),
    )
    style.configure(
        "Eyebrow.TLabel",
        background=palette.surface,
        foreground=palette.text_muted,
        font=(mono_family, SMALL_FONT_SIZE, "bold"),
    )
    style.configure(
        "EmptyTitle.TLabel",
        background=palette.preview,
        foreground=palette.text,
        font=(body_family, BODY_FONT_SIZE + 1, "bold"),
    )
    style.configure(
        "EmptyMuted.TLabel",
        background=palette.preview,
        foreground=palette.text_muted,
        font=small_font,
    )
    style.configure(
        "Muted.TLabel",
        background=palette.background,
        foreground=palette.text_muted,
        font=small_font,
    )
    style.configure(
        "Status.TLabel",
        background=palette.chrome,
        foreground=palette.text_muted,
        font=small_font,
        padding=(4, 2),
    )
    style.configure(
        "Header.TLabel",
        background=palette.chrome,
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

    style.configure(
        "TNotebook",
        background=palette.background,
        bordercolor=palette.background,
        lightcolor=palette.background,
        darkcolor=palette.background,
        borderwidth=0,
        tabmargins=(0, 0, 0, 0),
    )
    style.configure(
        "Nav.TNotebook",
        background=palette.chrome,
        bordercolor=palette.background,
        lightcolor=palette.background,
        darkcolor=palette.background,
        borderwidth=0,
        tabmargins=(8, 0, 0, 0),
    )
    style.configure(
        "Subnav.TNotebook",
        background=palette.chrome,
        bordercolor=palette.background,
        lightcolor=palette.background,
        darkcolor=palette.background,
        borderwidth=0,
        tabmargins=(8, 0, 0, 0),
    )
    style.configure(
        "Compact.TNotebook",
        background=palette.surface,
        bordercolor=palette.surface,
        lightcolor=palette.surface,
        darkcolor=palette.surface,
        borderwidth=0,
        tabmargins=(0, 0, 0, 0),
    )

    _configure_notebook_tab(
        style,
        root,
        style_name="TNotebook",
        shelf=palette.surface,
        selected_surface=palette.background,
        hover_surface=palette.surface_raised,
        font=tab_font,
        padding=(11, 6),
        selected_foreground=palette.text,
    )
    _configure_notebook_tab(
        style,
        root,
        style_name="Nav.TNotebook",
        shelf=palette.chrome,
        selected_surface=palette.background,
        hover_surface=palette.surface,
        font=tab_font,
        padding=(14, 7),
        selected_foreground=palette.text,
    )
    _configure_notebook_tab(
        style,
        root,
        style_name="Subnav.TNotebook",
        shelf=palette.chrome,
        selected_surface=palette.background,
        hover_surface=palette.surface,
        font=tab_font,
        padding=(12, 6),
        selected_foreground=palette.text,
    )
    _configure_notebook_tab(
        style,
        root,
        style_name="Compact.TNotebook",
        shelf=palette.surface,
        selected_surface=palette.input,
        hover_surface=palette.surface_raised,
        font=small_font,
        padding=(10, 5),
        selected_foreground=palette.text,
    )

    style.configure(
        "TButton",
        background=palette.surface_raised,
        foreground=palette.text,
        bordercolor=palette.surface_raised,
        lightcolor=palette.surface_raised,
        darkcolor=palette.surface_raised,
        borderwidth=0,
        focusthickness=1,
        focuscolor=palette.accent,
        padding=(10, 6),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[
            ("pressed", palette.selection),
            ("active", "#24282c"),
            ("disabled", palette.surface),
        ],
        foreground=[("disabled", palette.text_subtle)],
        bordercolor=[("focus", palette.accent), ("active", "#24282c")],
    )
    style.configure(
        "Tool.TButton",
        background=palette.surface_raised,
        foreground=palette.text,
        bordercolor=palette.surface_raised,
        padding=(9, 5),
        font=small_font,
    )
    style.configure(
        "Ghost.TButton",
        background=palette.surface,
        foreground=palette.text_muted,
        bordercolor=palette.surface,
        padding=(9, 5),
    )
    style.map(
        "Ghost.TButton",
        background=[("active", palette.surface_raised), ("pressed", palette.input)],
        foreground=[("active", palette.text), ("disabled", palette.text_subtle)],
        bordercolor=[("active", palette.surface_raised)],
    )
    style.configure(
        "Danger.TButton",
        background=palette.surface,
        foreground=palette.danger,
        bordercolor=palette.surface,
        padding=(9, 5),
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#342024"), ("pressed", "#451f24")],
        foreground=[("active", "#f0968e"), ("disabled", palette.text_subtle)],
        bordercolor=[("active", "#704047")],
    )
    style.configure(
        "Accent.TButton",
        background=palette.accent_surface,
        foreground=palette.accent,
        bordercolor=palette.accent_surface,
        lightcolor=palette.accent_surface,
        darkcolor=palette.accent_surface,
        font=medium_font,
        padding=(11, 6),
    )
    style.map(
        "Accent.TButton",
        background=[
            ("pressed", "#4a2d38"),
            ("active", palette.accent_surface_hover),
            ("disabled", palette.surface),
        ],
        foreground=[("active", palette.accent_hover), ("disabled", palette.text_subtle)],
        bordercolor=[("focus", palette.accent), ("disabled", palette.surface)],
    )

    style.layout(
        "Segment.TRadiobutton",
        [
            (
                "Radiobutton.padding",
                {
                    "sticky": "nsew",
                    "children": [("Radiobutton.label", {"sticky": "nsew"})],
                },
            )
        ],
    )
    style.configure(
        "Segment.TRadiobutton",
        background=palette.surface,
        foreground=palette.text_muted,
        bordercolor=palette.surface,
        borderwidth=0,
        relief="flat",
        padding=(12, 7),
        anchor="center",
    )
    style.map(
        "Segment.TRadiobutton",
        background=[
            ("selected active", palette.accent_surface_hover),
            ("selected", palette.accent_surface),
            ("active", palette.surface_raised),
        ],
        foreground=[
            ("selected", palette.accent),
            ("active", palette.text),
            ("disabled", palette.text_subtle),
        ],
        bordercolor=[("selected", palette.accent_surface), ("focus", palette.accent)],
    )

    for widget_style in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(
            widget_style,
            fieldbackground=palette.input,
            background=palette.input,
            foreground=palette.text,
            bordercolor=palette.input,
            lightcolor=palette.input,
            darkcolor=palette.input,
            insertcolor=palette.text,
            arrowcolor=palette.text_muted,
            padding=(7, 5),
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
            bordercolor=[("focus", palette.accent), ("active", palette.surface_raised)],
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
        bordercolor=palette.surface,
        borderwidth=0,
        relief="flat",
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
        bordercolor=palette.input,
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
        background=palette.chrome,
        foreground=palette.text_muted,
        bordercolor=palette.chrome,
        font=(mono_family, SMALL_FONT_SIZE, "bold"),
        padding=(7, 6),
        relief="flat",
    )
    style.map(
        "Treeview.Heading",
        background=[("active", palette.surface_raised)],
        foreground=[("active", palette.text)],
    )

    style.configure(
        "TScale",
        background=palette.surface,
        troughcolor=palette.input,
        bordercolor=palette.input,
        lightcolor=palette.accent,
        darkcolor=palette.accent,
        sliderlength=metric(14),
        sliderthickness=metric(14),
    )
    style.configure(
        "TProgressbar",
        background=palette.accent,
        troughcolor=palette.input,
        bordercolor=palette.input,
        lightcolor=palette.accent,
        darkcolor=palette.accent,
        thickness=metric(5),
    )
    style.configure(
        "TScrollbar",
        background=palette.surface_raised,
        troughcolor=palette.input,
        bordercolor=palette.input,
        arrowcolor=palette.text_muted,
        arrowsize=metric(10),
        width=metric(11),
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
        "highlightbackground": palette.input if not log else palette.preview,
        "highlightcolor": palette.accent,
        "highlightthickness": 1,
        "relief": "flat",
    }
