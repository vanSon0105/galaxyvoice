from __future__ import annotations

import sys
import tkinter as tk
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.gui import GalaxyStudioApp  # noqa: E402


class GuiLayoutTests(unittest.TestCase):
    def test_right_panel_direct_children_fit_small_window(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            root.geometry("900x600")
            GalaxyStudioApp(root)
            root.update_idletasks()
            root.update()

            shell = root.winfo_children()[0]
            right_panel = _find_grid_child(shell, row=1, column=1)
            self.assertIsNotNone(right_panel)

            right_height = right_panel.winfo_height()
            content_bottom = max(
                child.winfo_y() + child.winfo_height()
                for child in right_panel.winfo_children()
                if child.winfo_ismapped()
            )

            self.assertLessEqual(content_bottom, right_height)
        finally:
            root.destroy()


def _find_grid_child(parent: tk.Misc, row: int, column: int) -> tk.Widget | None:
    for child in parent.winfo_children():
        info = child.grid_info()
        if info.get("row") == row and info.get("column") == column:
            return child
    return None


if __name__ == "__main__":
    unittest.main()
