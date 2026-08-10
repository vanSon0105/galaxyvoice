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

    def test_voice_tab_contains_all_omnivoice_workspaces(self) -> None:
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
                    "Batch Voice",
                    "Long-form",
                    "Thư viện giọng",
                    "LoRA",
                    "Model & Runtime",
                ],
            )
            for tab in (
                app.omnivoice_auto_tab,
                app.omnivoice_clone_tab,
                app.omnivoice_design_tab,
                app.omnivoice_batch_tab,
                app.omnivoice_long_form_tab,
                app.omnivoice_library_tab,
                app.omnivoice_lora_tab,
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

    def test_full_language_list_and_inline_controls_are_available(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            self.assertGreaterEqual(len(app.omnivoice_language_values), 647)

            editor = app.omnivoice_text_widgets["auto"]
            app.omnivoice_expression_choice.set("Cười")
            app._insert_omnivoice_expression("auto")
            with patch("app.omnivoice.advanced_gui.simpledialog.askstring", return_value="B EY1 S"):
                app._insert_omnivoice_pronunciation("auto", "cmu")

            self.assertEqual(editor.get("1.0", "end-1c"), "[laughter] [B EY1 S]")
        finally:
            root.destroy()

    def test_generation_options_include_flashinfer_and_lora(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.omnivoice_enable_flashinfer.set(True)
            app.omnivoice_flashinfer_cuda_graph.set(False)
            app.omnivoice_lora_adapter.set("C:/models/adapter")

            options = app._omnivoice_options("auto", "Xin chào", bulk=False)

            self.assertTrue(options.enable_flashinfer)
            self.assertFalse(options.flashinfer_cuda_graph)
            self.assertEqual(options.lora_adapter, "C:/models/adapter")
        finally:
            root.destroy()

    def test_batch_start_uses_batch_service_thread(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.omnivoice_batch_text.insert("1.0", "Câu một\nCâu hai")
            ready = OmniVoiceRuntimeStatus(
                installed=True,
                message="ready",
                python_path=Path("python.exe"),
            )
            with (
                patch("app.omnivoice.advanced_gui.inspect_runtime", return_value=ready),
                patch("app.omnivoice.gui.threading.Thread") as thread,
            ):
                app._start_omnivoice_bulk(False)

            self.assertEqual(thread.call_args.kwargs["target"], app._run_omnivoice_bulk)
            self.assertEqual(thread.call_args.kwargs["name"], "omnivoice-batch")
            thread.return_value.start.assert_called_once()
            for progress in app.omnivoice_progress_bars:
                progress.stop()
        finally:
            root.destroy()

    def test_stop_reaps_worker_outside_tk_thread(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app._active_task = "omnivoice_generation"
            with patch("app.omnivoice.gui.threading.Thread") as thread:
                app._stop_omnivoice()

            self.assertTrue(app._omnivoice_cancel_requested)
            self.assertEqual(thread.call_args.kwargs["target"], app.omnivoice_client.stop)
            self.assertEqual(thread.call_args.kwargs["name"], "omnivoice-stop")
            thread.return_value.start.assert_called_once()
        finally:
            root.destroy()

    def test_merged_lora_model_does_not_reapply_the_adapter(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.omnivoice_lora_adapter.set("C:/models/adapter")
            app._active_task = "omnivoice_lora_merge"

            handled = app._handle_omnivoice_event(
                "omnivoice_lora_merged",
                {"output_dir": "C:/models/merged"},
            )

            self.assertTrue(handled)
            self.assertEqual(app.omnivoice_model_id.get(), "C:/models/merged")
            self.assertEqual(app.omnivoice_lora_adapter.get(), "")
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
