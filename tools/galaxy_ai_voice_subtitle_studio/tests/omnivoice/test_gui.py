from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from app.gui import GalaxyStudioApp
from app.omnivoice.runtime import OmniVoiceRuntimeStatus


class OmniVoiceGuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_voice_tab_contains_all_phase_one_to_four_pages(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            root.geometry("1080x680")
            labels = [
                app.voice_feature_notebook.tab(tab_id, "text")
                for tab_id in app.voice_feature_notebook.tabs()
            ]

            self.assertEqual(
                labels,
                [
                    "Voice & Subtitle",
                    "Auto Voice",
                    "Nhái giọng",
                    "Thiết kế giọng",
                    "Thư viện giọng",
                    "Model & Runtime",
                ],
            )
            for tab in (
                app.omnivoice_auto_tab,
                app.omnivoice_clone_tab,
                app.omnivoice_design_tab,
                app.omnivoice_library_tab,
                app.omnivoice_runtime_tab,
            ):
                app.voice_feature_notebook.select(tab)
                root.update_idletasks()
                root.update()
                self.assertLessEqual(
                    tab.winfo_rooty() + tab.winfo_height(),
                    app.voice_tab.winfo_rooty() + app.voice_tab.winfo_height(),
                )
        finally:
            root.destroy()

    def test_language_entry_remains_editable_after_busy_cycle(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            language_combo = app.omnivoice_editable_combos[0]

            app._set_busy(True)
            self.assertEqual(str(language_combo.cget("state")), "disabled")
            app._set_busy(False)

            self.assertEqual(str(language_combo.cget("state")), "normal")
            self.assertEqual(str(app.omnivoice_profile_combo.cget("state")), "readonly")
        finally:
            root.destroy()

    def test_missing_runtime_redirects_generation_to_runtime_page(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            missing = OmniVoiceRuntimeStatus(
                installed=False,
                message="Runtime chưa được cài",
                python_path=Path("missing-python.exe"),
            )
            with (
                patch("app.omnivoice.gui.inspect_runtime", return_value=missing),
                patch("app.omnivoice.gui.messagebox.showerror") as show_error,
            ):
                app._start_omnivoice_generation("auto")

            show_error.assert_called_once()
            self.assertIsNone(app._active_task)
            self.assertEqual(
                app.voice_feature_notebook.select(),
                str(app.omnivoice_runtime_tab),
            )
        finally:
            root.destroy()

    def _root(self) -> tk.Tk:
        try:
            return tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")


if __name__ == "__main__":
    unittest.main()
