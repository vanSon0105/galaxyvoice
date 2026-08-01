from __future__ import annotations

import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.gui import GalaxyStudioApp  # noqa: E402
from app.config import AppConfig, load_app_config, save_app_config  # noqa: E402
from app.engine import GenerationOptions, GenerationResult  # noqa: E402
from app.srt import SubtitleCue  # noqa: E402
from app.subtitle_removal import BLUR_MODE, SubtitleRemovalResult  # noqa: E402
from app.transcription import VideoSubtitleDraft, VideoSubtitleResult  # noqa: E402
from app.translator import AITranslationOptions  # noqa: E402
from app.tts import EDGE_ENGINE_LABEL, EdgeTTS, Voice  # noqa: E402


class GuiLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._config_temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self._config_temp_dir.name) / "config.json"

    def tearDown(self) -> None:
        self._config_temp_dir.cleanup()

    def test_app_loads_and_saves_user_config_without_api_key(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "config.json"
                save_app_config(
                    AppConfig(
                        output_dir=r"D:\Saved Output",
                        voice_name="vi-VN-NamMinhNeural",
                        rate=2,
                        keep_segments=False,
                        video_source_language="en",
                        video_target_language="vi",
                        ai_provider="deepseek",
                        ai_model="deepseek-v4-flash",
                        ai_base_url="https://api.deepseek.com",
                        subtitle_removal_mode="fill",
                        subtitle_region_y=68,
                        subtitle_blur_strength=26,
                    ),
                    config_path,
                )

                app = GalaxyStudioApp(root, config_path=config_path)

                self.assertEqual(app.output_dir.get(), r"D:\Saved Output")
                self.assertEqual(app.voice_name.get(), "vi-VN-NamMinhNeural")
                self.assertEqual(app.rate.get(), 2)
                self.assertFalse(app.keep_segments.get())
                self.assertEqual(app.video_source_language.get(), "English")
                self.assertEqual(app.ai_provider.get(), "DeepSeek")
                self.assertEqual(app._removal_mode_code(), "fill")
                self.assertEqual(app.subtitle_region_y.get(), 68)
                self.assertEqual(app.subtitle_blur_strength.get(), 26)

                app.output_dir.set(r"D:\New Output")
                app.ai_api_key.set("must-not-be-saved")
                self.assertIsNotNone(app._config_save_after_id)
                root.after(400, root.quit)
                root.mainloop()
                saved = load_app_config(config_path)

                self.assertEqual(saved.output_dir, r"D:\New Output")
                self.assertEqual(saved.subtitle_removal_mode, "fill")
                self.assertEqual(saved.subtitle_region_y, 68)
                self.assertEqual(saved.subtitle_blur_strength, 26)
                self.assertNotIn("must-not-be-saved", config_path.read_text(encoding="utf-8"))
        finally:
            root.destroy()

    def test_edge_tts_is_the_default_voice_engine(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        voices = [
            Voice(name="vi-VN-HoaiMyNeural", culture="vi-VN", gender="Female", age=""),
            Voice(name="vi-VN-NamMinhNeural", culture="vi-VN", gender="Male", age=""),
        ]

        try:
            with patch("app.gui.EdgeTTS.initial_voices", return_value=voices):
                app = GalaxyStudioApp(root, config_path=self.config_path)

            self.assertEqual(app.tts_engine_name.get(), EDGE_ENGINE_LABEL)
            self.assertIsInstance(app.tts, EdgeTTS)
            self.assertEqual(app.voice_name.get(), "vi-VN-HoaiMyNeural")
        finally:
            root.destroy()

    def test_saved_edge_voice_outside_initial_list_is_restored(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "config.json"
                save_app_config(AppConfig(voice_name="en-US-AriaNeural"), config_path)
                app = GalaxyStudioApp(root, config_path=config_path)

                self.assertEqual(app.voice_name.get(), "en-US-AriaNeural")
                self.assertIn("en-US-AriaNeural", app.voice_combo.cget("values"))
                self.assertIsNotNone(app._voice_refresh_after_id)
        finally:
            root.destroy()

    def test_config_read_error_disables_automatic_saving(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            with (
                patch("app.gui.load_app_config", side_effect=PermissionError("locked")),
                patch("app.gui.save_app_config") as save_config,
            ):
                app = GalaxyStudioApp(root, config_path=self.config_path)
                app.output_dir.set(r"D:\Must Not Overwrite")
                app._save_config_now()

                self.assertFalse(app._config_save_enabled)
                save_config.assert_not_called()
                self.assertIn("automatic config saving is disabled", app.log_text.get("1.0", "end"))
        finally:
            root.destroy()

    def test_right_panel_direct_children_fit_small_window(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            root.geometry("900x600")
            root.update_idletasks()
            root.update()

            right_panel = _find_grid_child(app.voice_tab, row=0, column=1)
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

    def test_main_tabs_separate_voice_and_subtitle_removal(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)

            labels = [app.main_notebook.tab(tab_id, "text") for tab_id in app.main_notebook.tabs()]
            self.assertEqual(labels, ["Voice", "Xóa phụ đề"])
            self.assertEqual(app.removal_preview_canvas.cget("width"), "480")
            self.assertEqual(app._removal_mode_code(), BLUR_MODE)
        finally:
            root.destroy()

    def test_subtitle_removal_tab_fits_at_minimum_window_size(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            root.geometry("900x600")
            app.main_notebook.select(app.removal_tab)
            root.update_idletasks()
            root.update()

            preview_holder = app.removal_preview_canvas.master
            canvas_right = app.removal_preview_canvas.winfo_x() + app.removal_preview_canvas.winfo_width()
            self.assertLessEqual(canvas_right, preview_holder.winfo_width())
            controls_panel = _find_grid_child(app.removal_tab, row=0, column=1)
            self.assertIsNotNone(controls_panel)
            controls_right = controls_panel.winfo_x() + controls_panel.winfo_width()
            self.assertLessEqual(controls_right, app.removal_tab.winfo_width())
        finally:
            root.destroy()

    def test_start_subtitle_removal_builds_options_for_the_worker(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.removal_video_path.set("clip.mp4")
            app.removal_project_name.set("clean-clip")
            app.subtitle_region_y.set(72)
            app.subtitle_blur_strength.set(22)

            with (
                patch("app.gui.threading.Thread") as thread,
                patch.object(app.removal_progress, "start"),
            ):
                app.start_remove_subtitles()

            self.assertEqual(thread.call_args.kwargs["target"], app._run_subtitle_removal)
            options = thread.call_args.kwargs["args"][0]
            self.assertEqual(options.video_path, Path("clip.mp4"))
            self.assertEqual(options.project_name, "clean-clip")
            self.assertEqual(options.mode, BLUR_MODE)
            self.assertEqual(options.region_y, 72)
            self.assertEqual(options.blur_strength, 22)
            thread.return_value.start.assert_called_once()
        finally:
            root.destroy()

    def test_subtitle_removal_success_enables_its_output_button(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        result = SubtitleRemovalResult(
            project_dir=Path("exports") / "clean-clip",
            video_path=Path("exports") / "clean-clip" / "clean-clip_no_subtitles.mp4",
            manifest_path=Path("exports") / "clean-clip" / "subtitle_removal_manifest.json",
            mode=BLUR_MODE,
            warnings=[],
        )

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app._finish_success(result)

            self.assertEqual(str(app.removal_open_button.cget("state")), "normal")
            self.assertEqual(str(app.open_button.cget("state")), "disabled")
            self.assertIn("clean-clip_no_subtitles.mp4", app.log_text.get("1.0", "end"))
        finally:
            root.destroy()

    def test_video_subtitle_success_loads_script_and_selects_matching_voice(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        voices = [
            Voice(name="Microsoft David Desktop", culture="en-US", gender="Male", age="Adult"),
            Voice(name="Vietnamese Voice", culture="vi-VN", gender="Female", age="Adult"),
        ]

        try:
            with patch("app.gui.EdgeTTS.initial_voices", return_value=voices):
                app = GalaxyStudioApp(root, config_path=self.config_path)
                source_cues = (
                    SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hello."),
                    SubtitleCue(index=2, start_ms=1000, end_ms=2000, text="World."),
                )
                translated_cues = (
                    SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Xin chao."),
                    SubtitleCue(index=2, start_ms=1000, end_ms=2000, text="The gioi."),
                )
                result = VideoSubtitleDraft(
                    source_video=Path("clip.mp4"),
                    project_name="clip",
                    audio_path=Path("temp") / "speech.wav",
                    source_language="en",
                    target_language="vi",
                    whisper_model="base",
                    ai_provider="deepseek",
                    ai_model="deepseek-v4-flash",
                    ai_base_url="https://api.deepseek.com",
                    source_cues=source_cues,
                    translated_cues=translated_cues,
                    warnings=[],
                )

                app._finish_success(result)

                self.assertEqual(app.script_text.get("1.0", "end").strip(), "Xin chao.\nThe gioi.")
                self.assertEqual(app.source_subtitle_text.get("1.0", "end").strip(), result.source_srt_text.strip())
                self.assertEqual(
                    app.translated_subtitle_text.get("1.0", "end").strip(),
                    result.translated_srt_text.strip(),
                )
                tab_labels = [app.subtitle_notebook.tab(tab_id, "text") for tab_id in app.subtitle_notebook.tabs()]
                self.assertEqual(tab_labels, ["Script", "Sub gốc", "Sub dịch"])
                self.assertEqual(str(app.subtitle_export_button.cget("state")), "normal")
                self.assertEqual(str(app.open_button.cget("state")), "disabled")
                self.assertEqual(app.voice_name.get(), "Vietnamese Voice")
        finally:
            root.destroy()

    def test_export_subtitles_uses_the_current_text_from_both_subtitle_tabs(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        draft = VideoSubtitleDraft(
            source_video=Path("clip.mp4"),
            project_name="clip",
            audio_path=Path("temp") / "speech.wav",
            source_language="en",
            target_language="vi",
            whisper_model="base",
            ai_provider="deepseek",
            ai_model="deepseek-v4-flash",
            ai_base_url="https://api.deepseek.com",
            source_cues=(SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Hello."),),
            translated_cues=(SubtitleCue(index=1, start_ms=0, end_ms=1000, text="Xin chao."),),
            warnings=[],
        )

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app._finish_success(draft)
            app._set_editor_text(
                app.source_subtitle_text,
                "1\n00:00:00,000 --> 00:00:01,000\nEdited original.\n",
            )
            app._set_editor_text(
                app.translated_subtitle_text,
                "1\n00:00:00,000 --> 00:00:01,000\nBan dich da sua.\n",
            )

            with patch("app.gui.threading.Thread") as thread:
                app.start_export_subtitles()

            self.assertEqual(thread.call_args.kwargs["target"], app._run_subtitle_export)
            export_args = thread.call_args.kwargs["args"]
            self.assertIn("Edited original.", export_args[3])
            self.assertIn("Ban dich da sua.", export_args[4])
            thread.return_value.start.assert_called_once()
            app.progress.stop()
        finally:
            root.destroy()

    def test_closing_during_export_defers_subtitle_workspace_cleanup_to_worker(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        app = GalaxyStudioApp(root, config_path=self.config_path)
        draft = Mock(spec=VideoSubtitleDraft)
        app.subtitle_draft = draft
        app._export_in_progress = True

        root.destroy()

        draft.cleanup.assert_not_called()

    def test_export_worker_cleans_subtitle_workspace_after_app_closes(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            draft = Mock(spec=VideoSubtitleDraft)
            app._closing = True
            with patch("app.gui.export_subtitle_package", side_effect=OSError("closed")):
                app._run_subtitle_export(draft, Path("exports"), "clip", "source", "translated")

            draft.cleanup.assert_called_once()
        finally:
            root.destroy()

    def test_closing_after_create_worker_finishes_cleans_pending_draft(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        app = GalaxyStudioApp(root, config_path=self.config_path)
        draft = Mock(spec=VideoSubtitleDraft)
        with patch("app.gui.prepare_subtitles_from_video", return_value=draft):
            app._run_video_subtitles(Mock())

        root.destroy()

        draft.cleanup.assert_called_once()

    def test_create_worker_cleans_draft_instead_of_enqueueing_after_app_closes(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app._closing = True
            draft = Mock(spec=VideoSubtitleDraft)
            with patch("app.gui.prepare_subtitles_from_video", return_value=draft):
                app._run_video_subtitles(Mock())

            draft.cleanup.assert_called_once()
            self.assertTrue(app.events.empty())
        finally:
            root.destroy()

    def test_generation_translates_known_script_language_before_tts(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        result = GenerationResult(
            project_dir=Path("exports") / "clip",
            wav_path=Path("exports") / "clip" / "clip.wav",
            srt_path=Path("exports") / "clip" / "clip.srt",
            mp3_path=None,
            manifest_path=Path("exports") / "clip" / "manifest.json",
            cue_count=1,
            total_duration_ms=1000,
            warnings=[],
        )

        try:
            with patch("app.gui.EdgeTTS.initial_voices", return_value=[]):
                app = GalaxyStudioApp(root, config_path=self.config_path)
                options = GenerationOptions(text="Hello.", output_dir=Path("exports"), project_name="clip")
                translation_options = AITranslationOptions(
                    source_language="en",
                    target_language="vi",
                    api_key="test-key",
                )

                with patch("app.gui.translate_script_text", return_value="Xin chao.") as translate:
                    with patch("app.gui.generate_package", return_value=result) as generate:
                        app._run_generation(options, translation_options)

                translate.assert_called_once()
                generated_options = generate.call_args.args[0]
                self.assertEqual(generated_options.text, "Xin chao.")

                events = []
                while not app.events.empty():
                    events.append(app.events.get_nowait())
                self.assertIn(("script_translated", ("Xin chao.", "vi")), events)
        finally:
            root.destroy()

    def test_start_generate_selects_target_voice_before_worker_starts(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        voices = [
            Voice(name="English Voice", culture="en-US", gender="Male", age="Adult"),
            Voice(name="Vietnamese Voice", culture="vi-VN", gender="Female", age="Adult"),
        ]

        try:
            with patch("app.gui.EdgeTTS.initial_voices", return_value=voices):
                app = GalaxyStudioApp(root, config_path=self.config_path)
                app.script_text.insert("1.0", "Hello.")
                app.script_language_code = "en"
                app.voice_name.set("English Voice")
                app.ai_api_key.set("test-key")

                with patch("app.gui.threading.Thread") as thread:
                    app.start_generate()

                generation_options, translation_options, tts_engine = thread.call_args.kwargs["args"]
                self.assertEqual(generation_options.voice_name, "Vietnamese Voice")
                self.assertEqual(translation_options.target_language, "vi")
                self.assertIs(tts_engine, app.tts)
                thread.return_value.start.assert_called_once()
        finally:
            root.destroy()

    def test_refresh_voices_runs_outside_the_tk_thread(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            with patch("app.gui.threading.Thread") as thread:
                app.refresh_voices()

            self.assertEqual(thread.call_args.kwargs["target"], app._run_voice_refresh)
            self.assertEqual(thread.call_args.kwargs["args"], (app.tts,))
            thread.return_value.start.assert_called_once()
        finally:
            root.destroy()

    def test_subtitle_progress_event_updates_status_and_progress_bar(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.events.put(("task_progress", ("Translating", 240, 768)))

            app._poll_events()

            self.assertEqual(app.status.get(), "Translating 240/768")
            self.assertEqual(str(app.progress.cget("mode")), "determinate")
            self.assertEqual(float(app.progress.cget("maximum")), 768.0)
            self.assertEqual(float(app.progress.cget("value")), 240.0)
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
