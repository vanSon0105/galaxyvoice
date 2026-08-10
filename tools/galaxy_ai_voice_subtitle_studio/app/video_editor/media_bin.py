from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from .model import AUDIO_ASSET, SUBTITLE_ASSET, VIDEO_ASSET, EditorAsset


ASSET_KIND_LABELS = {
    VIDEO_ASSET: "Video",
    AUDIO_ASSET: "Audio",
    SUBTITLE_ASSET: "SRT",
}


class EditorMediaBin(ttk.Frame):
    """Imported editor assets with desktop drag-and-drop callbacks."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_drop: Callable[[str, int, int], None],
        on_activate: Callable[[str], None],
        on_remove: Callable[[str], None],
    ) -> None:
        super().__init__(master, style="Surface.TFrame")
        self.on_drop = on_drop
        self.on_activate = on_activate
        self.on_remove = on_remove
        self.assets: dict[str, EditorAsset] = {}
        self._drag_asset_id: str | None = None
        self._drag_origin: tuple[int, int] | None = None
        self._drag_window: tk.Toplevel | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text="Tệp phương tiện", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 7)
        )

        self.tree = ttk.Treeview(
            self,
            columns=("detail",),
            show="tree headings",
            selectmode="browse",
            height=8,
        )
        self.tree.heading("#0", text="Tệp")
        self.tree.heading("detail", text="Thông tin")
        self.tree.column("#0", width=130, minwidth=90)
        self.tree.column("detail", width=92, minwidth=65, anchor="e")
        self.tree.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        actions = ttk.Frame(self, style="Surface.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        actions.columnconfigure(0, weight=1)
        self.insert_button = ttk.Button(actions, text="Đưa vào timeline", command=self._activate_selected)
        self.insert_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.remove_button = ttk.Button(actions, text="Gỡ", command=self._remove_selected, width=6)
        self.remove_button.grid(row=0, column=1)

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<ButtonPress-1>", self._on_press)
        self.tree.bind("<B1-Motion>", self._on_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_release)

    def add_asset(self, asset: EditorAsset, *, select: bool = True) -> None:
        self.assets[asset.asset_id] = asset
        values = (asset_detail(asset),)
        text = f"{ASSET_KIND_LABELS[asset.kind]}  {asset.name}"
        if self.tree.exists(asset.asset_id):
            self.tree.item(asset.asset_id, text=text, values=values)
        else:
            self.tree.insert("", "end", iid=asset.asset_id, text=text, values=values)
        if select:
            self.tree.selection_set(asset.asset_id)
            self.tree.focus(asset.asset_id)
            self.tree.see(asset.asset_id)

    def remove_asset(self, asset_id: str) -> None:
        self.assets.pop(asset_id, None)
        if self.tree.exists(asset_id):
            self.tree.delete(asset_id)

    def selected_asset_id(self) -> str | None:
        selected = self.tree.selection()
        return selected[0] if selected else None

    def _activate_selected(self) -> None:
        asset_id = self.selected_asset_id()
        if asset_id:
            self.on_activate(asset_id)

    def _remove_selected(self) -> None:
        asset_id = self.selected_asset_id()
        if asset_id:
            self.on_remove(asset_id)

    def _on_double_click(self, event: tk.Event) -> None:
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.on_activate(item)

    def _on_press(self, event: tk.Event) -> None:
        item = self.tree.identify_row(event.y)
        self._drag_asset_id = item or None
        self._drag_origin = (event.x_root, event.y_root) if item else None
        if item:
            self.tree.selection_set(item)

    def _on_motion(self, event: tk.Event) -> None:
        if not self._drag_asset_id or not self._drag_origin:
            return
        distance = math.hypot(
            event.x_root - self._drag_origin[0],
            event.y_root - self._drag_origin[1],
        )
        if self._drag_window is None and distance < 6:
            return
        if self._drag_window is None:
            asset = self.assets.get(self._drag_asset_id)
            if asset is None:
                return
            self._drag_window = tk.Toplevel(self)
            self._drag_window.overrideredirect(True)
            try:
                self._drag_window.attributes("-topmost", True)
                self._drag_window.attributes("-alpha", 0.92)
            except tk.TclError:
                pass
            ttk.Label(
                self._drag_window,
                text=f"{ASSET_KIND_LABELS[asset.kind]}  {asset.name}",
                padding=(9, 5),
                relief="solid",
            ).pack()
        self._drag_window.geometry(f"+{event.x_root + 12}+{event.y_root + 12}")

    def _on_release(self, event: tk.Event) -> None:
        asset_id = self._drag_asset_id
        was_dragging = self._drag_window is not None
        self._destroy_drag_window()
        self._drag_asset_id = None
        self._drag_origin = None
        if was_dragging and asset_id:
            self.on_drop(asset_id, event.x_root, event.y_root)

    def _destroy_drag_window(self) -> None:
        if self._drag_window is not None:
            try:
                self._drag_window.destroy()
            except tk.TclError:
                pass
            self._drag_window = None


def asset_detail(asset: EditorAsset) -> str:
    if asset.kind == VIDEO_ASSET:
        return f"{asset.width}x{asset.height}  {asset.fps:.1f}fps"
    if asset.kind == AUDIO_ASSET:
        return _duration_text(asset.duration_seconds)
    return f"{len(asset.cues)} cue"


def _duration_text(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"
