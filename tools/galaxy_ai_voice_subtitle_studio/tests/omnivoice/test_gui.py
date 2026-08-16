from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from app.gui import GalaxyStudioApp
from app.omnivoice.runtime import OmniVoiceRuntimeStatus
from app.voice.srt import SubtitleCue, render_srt
from app.voice.transcription import VideoSubtitleDraft


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
                    "VoiceStudio",
                    "Clone",
                    "Design",
                    "Dubbing",
                    "Truyện & Sách nói",
                    "Gallery",
                    "Transcripts",
                ],
            )
            for tab in (
                app.omnivoice_clone_tab,
                app.omnivoice_design_tab,
                app.classic_voice_tab,
                app.omnivoice_longform_tab,
                app.omnivoice_gallery_tab,
                app.omnivoice_transcripts_tab,
            ):
                app.voice_feature_notebook.select(tab)
                root.update_idletasks()
                root.update()
                self.assertLessEqual(
                    tab.winfo_rooty() + tab.winfo_height(),
                    app.voice_tab.winfo_rooty() + app.voice_tab.winfo_height(),
                )

            gallery_tools = [
                app.omnivoice_gallery_notebook.tab(tab_id, "text")
                for tab_id in app.omnivoice_gallery_notebook.tabs()
            ]
            self.assertEqual(
                gallery_tools,
                [
                    "Presets",
                    "Giọng đã lưu",
                    "Auto Voice",
                    "Batch",
                    "LoRA",
                    "Runtime",
                    "Lịch sử tạo",
                ],
            )
        finally:
            root.destroy()

    def test_longform_workspace_switches_mode_and_carries_the_project(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.voice_feature_notebook.select(app.omnivoice_longform_tab)
            root.update_idletasks()

            self.assertEqual(app.omnivoice_longform_workspace_mode.get(), "stories")
            self.assertEqual(app.omnivoice_stories_tab.winfo_manager(), "grid")
            self.assertEqual(app.omnivoice_audiobook_tab.winfo_manager(), "")

            script = "# Mở đầu\nLan: Xin chào."
            app.omnivoice_stories_text.insert("1.0", script)
            app.omnivoice_story_cast["Lan"] = "profile-lan"

            app._select_omnivoice_longform_mode("audiobook")

            self.assertEqual(app.omnivoice_longform_workspace_mode.get(), "audiobook")
            self.assertEqual(app.omnivoice_stories_tab.winfo_manager(), "")
            self.assertEqual(app.omnivoice_audiobook_tab.winfo_manager(), "grid")
            converted = app.omnivoice_audiobook_text.get("1.0", "end").strip()
            self.assertIn("# Mở đầu", converted)
            self.assertIn("[voice:Lan] Xin chào.", converted)
            self.assertEqual(app.omnivoice_audiobook_cast, {"Lan": "profile-lan"})
            self.assertEqual(
                app.omnivoice_workspace_documents["audiobook"].items[0].text,
                "Xin chào.",
            )

            app.omnivoice_audiobook_text.delete("1.0", "end")
            app.omnivoice_audiobook_text.insert(
                "1.0",
                "# Kết thúc\n[voice:Minh] Tạm biệt.",
            )
            app._select_omnivoice_longform_mode("stories")

            converted_back = app.omnivoice_stories_text.get("1.0", "end").strip()
            self.assertIn("# Kết thúc", converted_back)
            self.assertIn("Minh: Tạm biệt.", converted_back)
        finally:
            root.destroy()

    def test_longform_workspace_can_auto_detect_audiobook_mode(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.omnivoice_stories_text.insert(
                "1.0",
                "# Chương 1\nMở đầu.\n# Chương 2\nTiếp tục.",
            )

            app._auto_select_omnivoice_longform_mode()

            self.assertEqual(app.omnivoice_longform_workspace_mode.get(), "audiobook")
            self.assertEqual(app.omnivoice_audiobook_tab.winfo_manager(), "grid")

            app.omnivoice_audiobook_text.delete("1.0", "end")
            app.omnivoice_audiobook_text.insert(
                "1.0",
                "# Mở đầu\nLan: Xin chào.\nMinh: Đi thôi.",
            )
            app._auto_select_omnivoice_longform_mode()

            self.assertEqual(app.omnivoice_longform_workspace_mode.get(), "stories")
            story_script = app.omnivoice_stories_text.get("1.0", "end").strip()
            self.assertIn("Lan: Xin chào.", story_script)
            self.assertIn("Minh: Đi thôi.", story_script)
            self.assertEqual(
                [
                    item.speaker
                    for item in app.omnivoice_workspace_documents["stories"].items
                ],
                ["Lan", "Minh"],
            )
        finally:
            root.destroy()

    def test_longform_project_saves_both_modes_under_one_project_id(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.omnivoice_story_project_name.set("Du an dai tap")
            app.omnivoice_stories_text.insert("1.0", "# Mở đầu\nLan: Xin chào.")
            app._save_workspace_project("stories")

            app._select_omnivoice_longform_mode("audiobook")
            app.omnivoice_audiobook_title.set("Sách thử nghiệm")
            app._save_workspace_project("audiobook")

            projects = app.omnivoice_workspace_repository.list_projects("longform")
            self.assertEqual(len(projects), 1)
            project = projects[0]
            self.assertEqual(project.payload["active_mode"], "audiobook")
            self.assertEqual(set(project.payload["modes"]), {"stories", "audiobook"})
            self.assertEqual(
                project.payload["modes"]["audiobook"]["title"],
                "Sách thử nghiệm",
            )
            self.assertEqual(
                app.omnivoice_workspace_project_ids,
                {"stories": project.project_id, "audiobook": project.project_id},
            )

            app.omnivoice_audiobook_text.delete("1.0", "end")
            app.omnivoice_audiobook_title.set("")
            app._select_omnivoice_longform_mode("stories", sync_project=False)
            app._restore_workspace_project("stories", project)

            self.assertEqual(app.omnivoice_longform_workspace_mode.get(), "audiobook")
            self.assertEqual(app.omnivoice_audiobook_title.get(), "Sách thử nghiệm")
            self.assertIn(
                "[voice:Lan] Xin chào.",
                app.omnivoice_audiobook_text.get("1.0", "end").strip(),
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

    def test_dubbing_uses_current_edited_translated_subtitles(self) -> None:
        root = self._root()
        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.subtitle_draft = VideoSubtitleDraft(
                source_video=Path("video.mp4"),
                project_name="dub-test",
                audio_path=Path("speech.wav"),
                source_language="zh",
                target_language="vi",
                whisper_model="base",
                ai_provider="deepseek",
                ai_model="deepseek-chat",
                ai_base_url="https://api.deepseek.com",
                source_cues=(SubtitleCue(1, 0, 1_000, "你好"),),
                translated_cues=(SubtitleCue(1, 0, 1_000, "Xin chào"),),
                warnings=[],
            )
            app.translated_subtitle_text.delete("1.0", "end")
            app.translated_subtitle_text.insert(
                "1.0",
                render_srt([SubtitleCue(1, 0, 1_500, "Bản dịch đã sửa")]),
            )
            ready = OmniVoiceRuntimeStatus(
                installed=True,
                message="ready",
                python_path=Path("python.exe"),
            )
            with (
                patch("app.omnivoice.workspaces.gui.inspect_runtime", return_value=ready),
                patch("app.omnivoice.gui.threading.Thread") as thread,
            ):
                app.start_omnivoice_dubbing()

            self.assertEqual(app._active_task, "omnivoice_dub")
            plan = thread.call_args.kwargs["args"][2]
            speech = next(span for span in plan.spans if span.text)
            self.assertEqual(speech.text, "Bản dịch đã sửa")
            self.assertEqual(speech.duration, 1.5)
            thread.return_value.start.assert_called_once()
            for progress in app.omnivoice_progress_bars:
                progress.stop()
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
                str(app.omnivoice_gallery_tab),
            )
            self.assertEqual(
                app.omnivoice_gallery_notebook.select(),
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
