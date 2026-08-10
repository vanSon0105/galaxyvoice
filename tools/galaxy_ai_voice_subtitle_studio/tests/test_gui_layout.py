from __future__ import annotations

import io
import sys
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.gui import GalaxyStudioApp  # noqa: E402
from app.common.config import AppConfig, load_app_config, save_app_config  # noqa: E402
from app.voice.engine import GenerationOptions, GenerationResult  # noqa: E402
from app.voice.srt import SubtitleCue  # noqa: E402
from app.subtitle_removal.service import (  # noqa: E402
    AI_INPAINT_MODE,
    BLUR_MODE,
    FAST_AI_INPAINT_MODE,
    SubtitleRemovalResult,
)
from app.voice.transcription import VideoSubtitleDraft, VideoSubtitleResult  # noqa: E402
from app.voice.translator import AITranslationOptions  # noqa: E402
from app.voice.tts import EDGE_ENGINE_LABEL, EdgeTTS, Voice  # noqa: E402


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
                        voice_processing_device="cpu",
                        removal_processing_device="cuda",
                        propainter_license_accepted=True,
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
                self.assertEqual(app.voice_processing_device.get(), "CPU (không dùng GPU)")
                self.assertEqual(app.removal_processing_device.get(), "NVIDIA GPU rời")

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
                self.assertEqual(saved.voice_processing_device, "cpu")
                self.assertEqual(saved.removal_processing_device, "cuda")
                self.assertTrue(saved.propainter_license_accepted)
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
            with patch("app.voice.tts.EdgeTTS.initial_voices", return_value=voices):
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

    def test_main_tabs_include_full_audio_separation_workspace(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)

            labels = [app.main_notebook.tab(tab_id, "text") for tab_id in app.main_notebook.tabs()]
            self.assertEqual(labels, ["Voice", "Tách âm thanh", "Xóa phụ đề"])
            self.assertEqual(app.audio_format.get(), "WAV")
            self.assertIn("MDX-Net", app.audio_method_combo.cget("values"))
            self.assertIn("Intel / AMD DirectML", app.audio_device_combo.cget("values"))
            self.assertEqual(str(app.audio_stop_button.cget("state")), "disabled")
            self.assertEqual(
                tuple(app.audio_model_combo.cget("values")),
                tuple(model.label for model in app._audio_models_for_method()),
            )
            self.assertEqual(app.removal_preview_canvas.cget("width"), "480")
            self.assertEqual(app._removal_mode_code(), BLUR_MODE)
            self.assertIn("AI ProPainter", app.removal_mode_combo.cget("values"))
            self.assertIn("Fast AI (tối ưu)", app.removal_mode_combo.cget("values"))
            self.assertEqual(str(app.voice_device_combo.cget("state")), "readonly")
            self.assertEqual(str(app.removal_device_combo.cget("state")), "disabled")
            app.removal_mode.set("AI ProPainter")
            app._on_removal_mode_changed()
            self.assertEqual(str(app.removal_device_combo.cget("state")), "readonly")
            app.removal_mode.set("Fast AI (tối ưu)")
            app._on_removal_mode_changed()
            self.assertEqual(str(app.removal_device_combo.cget("state")), "readonly")
        finally:
            root.destroy()

    def test_audio_separation_tab_fits_at_minimum_window_size(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            root.geometry("900x600")
            app.main_notebook.select(app.audio_tab)
            root.update_idletasks()
            root.update()

            self.assertFalse(app.log_frame.winfo_ismapped())
            self.assertTrue(app.audio_log_text.winfo_ismapped())
            tab_bottom = app.audio_tab.winfo_rooty() + app.audio_tab.winfo_height()
            for widget in (
                app.audio_input_browse_button,
                app.audio_preset_combo,
                app.audio_sample_check,
                app.audio_stop_button,
                app.audio_log_text,
            ):
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), tab_bottom)
        finally:
            root.destroy()

    def test_audio_method_and_single_stem_controls_stay_consistent(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.audio_method.set("VR Architecture")
            app._on_audio_method_changed()
            self.assertEqual(app.audio_segment_label.get(), "Window Size")
            self.assertEqual(app.audio_overlap_label.get(), "Aggression")

            app.audio_instrumental_only.set(True)
            app.audio_vocals_only.set(True)
            app._on_audio_vocals_changed()
            self.assertTrue(app.audio_vocals_only.get())
            self.assertFalse(app.audio_instrumental_only.get())
        finally:
            root.destroy()

    def test_audio_progress_uses_percentage_reported_by_the_engine(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app._update_audio_progress_from_message("Processing audio 47%|####")

            self.assertEqual(str(app.audio_progress.cget("mode")), "determinate")
            self.assertEqual(float(app.audio_progress.cget("value")), 47.0)
            self.assertEqual(app.status.get(), "Separating audio 47%")
        finally:
            root.destroy()

    def test_audio_custom_preset_is_saved_and_can_be_applied(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.audio_format.set("MP3")
            app.audio_sample_mode.set(True)
            app.audio_vocals_only.set(True)
            with patch("app.audio_separation.gui.simpledialog.askstring", return_value="Podcast Voice"):
                app.save_current_audio_preset()

            self.assertIn("Podcast Voice", app.audio_preset_combo.cget("values"))
            self.assertTrue(app.audio_presets_path.is_file())

            app.audio_format.set("WAV")
            app.audio_sample_mode.set(False)
            app.audio_vocals_only.set(False)
            app.audio_saved_setting.set("Podcast Voice")
            app._on_audio_preset_changed()

            self.assertEqual(app.audio_format.get(), "MP3")
            self.assertTrue(app.audio_sample_mode.get())
            self.assertTrue(app.audio_vocals_only.get())
        finally:
            root.destroy()

    def test_closing_app_terminates_active_media_processes(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        app = GalaxyStudioApp(root, config_path=self.config_path)
        with patch("app.gui.managed_media_processes.terminate_all") as terminate:
            root.destroy()
        terminate.assert_called_once_with()

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
            transport = app.removal_play_button.master
            preview_panel = transport.master
            transport_bottom = transport.winfo_y() + transport.winfo_height()
            self.assertLessEqual(transport_bottom, preview_panel.winfo_height())
            controls_panel = _find_grid_child(app.removal_tab, row=0, column=1)
            self.assertIsNotNone(controls_panel)
            controls_right = controls_panel.winfo_x() + controls_panel.winfo_width()
            self.assertLessEqual(controls_right, app.removal_tab.winfo_width())
            device_row = app.removal_device_combo.master
            device_right = max(
                child.winfo_x() + child.winfo_width()
                for child in device_row.winfo_children()
            )
            self.assertLessEqual(device_right, device_row.winfo_width())
        finally:
            root.destroy()

    def test_subtitle_removal_tab_has_video_playback_controls(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)

            self.assertEqual(app.removal_play_button.cget("text"), "Phát")
            self.assertEqual(str(app.removal_play_button.cget("state")), "disabled")
            self.assertEqual(str(app.removal_timeline.cget("state")), "disabled")
            self.assertEqual(app.removal_time_text.get(), "00:00 / 00:00")
        finally:
            root.destroy()

    def test_start_video_playback_streams_from_current_timeline_position(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.removal_video_path.set("clip.mp4")
            app.removal_duration_seconds = 20.0
            app.removal_timeline_position.set(6.5)
            process = Mock()
            process.poll.return_value = None

            with (
                patch("app.subtitle_removal.gui.find_ffmpeg", return_value="ffmpeg"),
                patch("app.subtitle_removal.gui.find_ffplay", return_value=None),
                patch("app.subtitle_removal.gui.subprocess.Popen", return_value=process) as popen,
                patch("app.subtitle_removal.gui.threading.Thread") as thread,
            ):
                app.toggle_removal_playback()

            command = popen.call_args.args[0]
            self.assertEqual(command[command.index("-ss") + 1], "6.500")
            self.assertEqual(command[-1], "pipe:1")
            self.assertEqual(app.removal_play_button.cget("text"), "Tạm dừng")
            thread.return_value.start.assert_called_once()
            app._playback_process = None
        finally:
            root.destroy()

    def test_stale_video_preview_event_is_ignored_after_source_changes(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.removal_video_path.set("new.mp4")
            app._removal_preview_session = 2
            app.events.put(
                (
                    "removal_preview_ready",
                    (1, "old.mp4", "old-preview.png", 12.0, 0.0),
                )
            )

            with patch.object(app, "_load_removal_preview") as load_preview:
                app._poll_events()

            load_preview.assert_not_called()
        finally:
            root.destroy()

    def test_playback_decoder_failure_is_reported_as_an_error_event(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.removal_duration_seconds = 10.0
            process = Mock()
            process.stdout = io.BytesIO()
            process.stderr = io.BytesIO(b"decoder failed")
            process.wait.return_value = 1

            app._read_removal_playback_frames(
                process,
                threading.Event(),
                session=3,
                start_seconds=0.0,
            )

            self.assertEqual(
                app.events.get_nowait(),
                ("removal_playback_error", (3, "decoder failed")),
            )
        finally:
            root.destroy()

    def test_stopping_playback_reaps_processes_outside_the_tk_thread(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            video_process = Mock()
            video_process.poll.return_value = None
            audio_process = Mock()
            audio_process.poll.return_value = None
            app._playback_process = video_process
            app._playback_audio_process = audio_process

            with patch("app.subtitle_removal.gui.threading.Thread") as thread:
                app._stop_removal_playback()

            video_process.terminate.assert_called_once_with()
            audio_process.terminate.assert_called_once_with()
            video_process.wait.assert_not_called()
            audio_process.wait.assert_not_called()
            self.assertEqual(
                thread.call_args.kwargs["target"],
                app._reap_playback_processes,
            )
            thread.return_value.start.assert_called_once_with()
        finally:
            root.destroy()

    def test_playback_time_formats_long_videos(self) -> None:
        self.assertEqual(GalaxyStudioApp._format_playback_time(65.9), "01:05")
        self.assertEqual(GalaxyStudioApp._format_playback_time(3661), "01:01:01")

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
            app.removal_processing_device.set("CPU (không dùng GPU)")

            with (
                patch("app.subtitle_removal.gui.threading.Thread") as thread,
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
            self.assertEqual(options.processing_device, "cpu")
            thread.return_value.start.assert_called_once()
        finally:
            root.destroy()

    def test_start_fast_ai_builds_fast_mode_for_the_worker(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.removal_video_path.set("clip.mp4")
            app.removal_mode.set("Fast AI (tối ưu)")
            app.propainter_license_accepted.set(True)

            with (
                patch("app.subtitle_removal.propainter.resolve_propainter_runtime"),
                patch("app.subtitle_removal.gui.threading.Thread") as thread,
                patch.object(app.removal_progress, "start"),
            ):
                app.start_remove_subtitles()

            options = thread.call_args.kwargs["args"][0]
            self.assertEqual(options.mode, FAST_AI_INPAINT_MODE)
            thread.return_value.start.assert_called_once_with()
        finally:
            root.destroy()

    def test_start_video_subtitles_passes_selected_processing_device(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.video_path.set("clip.mp4")
            app.voice_processing_device.set("CPU (không dùng GPU)")

            with (
                patch("app.voice.gui.threading.Thread") as thread,
                patch.object(app.progress, "start"),
            ):
                app.start_create_video_subtitles()

            options = thread.call_args.kwargs["args"][0]
            self.assertEqual(options.processing_device, "cpu")
            thread.return_value.start.assert_called_once_with()
        finally:
            root.destroy()

    def test_ai_inpainting_requires_noncommercial_license_acceptance(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.removal_video_path.set("clip.mp4")
            app.removal_mode.set("AI ProPainter")

            with (
                patch("app.subtitle_removal.gui.messagebox.askyesno", return_value=False) as confirm,
                patch("app.subtitle_removal.gui.threading.Thread") as thread,
            ):
                app.start_remove_subtitles()

            confirm.assert_called_once()
            thread.assert_not_called()
        finally:
            root.destroy()

    def test_missing_propainter_offers_installer_before_video_processing(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.removal_video_path.set("clip.mp4")
            app.removal_mode.set("AI ProPainter")
            app.propainter_license_accepted.set(True)

            with (
                patch(
                    "app.subtitle_removal.propainter.resolve_propainter_runtime",
                    side_effect=RuntimeError("ProPainter is not installed completely."),
                ) as runtime_check,
                patch("app.subtitle_removal.gui.messagebox.askyesno", return_value=False) as install_prompt,
                patch("app.subtitle_removal.gui.threading.Thread") as thread,
            ):
                app.start_remove_subtitles()

            runtime_check.assert_called_once_with()
            install_prompt.assert_called_once()
            self.assertIn("cài ProPainter", install_prompt.call_args.args[1])
            thread.assert_not_called()
        finally:
            root.destroy()

    def test_missing_propainter_can_open_installer_from_preflight(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.removal_video_path.set("clip.mp4")
            app.removal_mode.set("AI ProPainter")
            app.propainter_license_accepted.set(True)

            with (
                patch(
                    "app.subtitle_removal.propainter.resolve_propainter_runtime",
                    side_effect=RuntimeError("ProPainter is not installed completely."),
                ),
                patch("app.subtitle_removal.gui.messagebox.askyesno", return_value=True),
                patch.object(app, "install_propainter") as install,
                patch("app.subtitle_removal.gui.threading.Thread") as thread,
            ):
                app.start_remove_subtitles()

            install.assert_called_once_with()
            thread.assert_not_called()
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
            with patch("app.voice.tts.EdgeTTS.initial_voices", return_value=voices):
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

            with patch("app.voice.gui.threading.Thread") as thread:
                app.start_export_subtitles()

            self.assertEqual(thread.call_args.kwargs["target"], app._run_subtitle_export)
            export_args = thread.call_args.kwargs["args"]
            self.assertIn("Edited original.", export_args[3])
            self.assertIn("Ban dich da sua.", export_args[4])
            thread.return_value.start.assert_called_once()
            app.progress.stop()
        finally:
            root.destroy()

    def test_closing_with_an_unexported_subtitle_draft_requires_confirmation(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.subtitle_draft = Mock(spec=VideoSubtitleDraft)
            app._subtitle_draft_dirty = True

            with (
                patch("app.voice.gui.messagebox.askyesno", return_value=False) as confirm,
                patch.object(app, "_save_config_now") as save_config,
                patch.object(root, "destroy") as destroy,
            ):
                app._close_app()

            confirm.assert_called_once()
            save_config.assert_not_called()
            destroy.assert_not_called()
        finally:
            root.destroy()

    def test_browsing_to_a_new_video_discards_the_confirmed_old_draft(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            draft = Mock(spec=VideoSubtitleDraft)
            app.subtitle_draft = draft
            app._subtitle_draft_dirty = True
            app.video_path.set("old.mp4")
            app._set_editor_text(app.source_subtitle_text, "old source")
            app._set_editor_text(app.translated_subtitle_text, "old translation")

            with (
                patch("app.voice.gui.filedialog.askopenfilename", return_value="new.mp4"),
                patch("app.voice.gui.messagebox.askyesno", return_value=True),
            ):
                app.browse_video()

            draft.cleanup.assert_called_once()
            self.assertIsNone(app.subtitle_draft)
            self.assertFalse(app._subtitle_draft_dirty)
            self.assertEqual(app.video_path.get(), "new.mp4")
            self.assertEqual(app.source_subtitle_text.get("1.0", "end-1c"), "")
            self.assertEqual(str(app.subtitle_export_button.cget("state")), "disabled")
        finally:
            root.destroy()

    def test_export_blocks_a_draft_from_a_different_manually_entered_video(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.subtitle_draft = Mock(
                spec=VideoSubtitleDraft,
                source_video=Path("old.mp4"),
            )
            app.video_path.set("new.mp4")

            with (
                patch("app.voice.gui.messagebox.showwarning") as warning,
                patch("app.voice.gui.threading.Thread") as thread,
            ):
                app.start_export_subtitles()

            warning.assert_called_once()
            thread.assert_not_called()
        finally:
            root.destroy()

    def test_export_completion_keeps_draft_dirty_if_it_changed_during_export(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        result = VideoSubtitleResult(
            project_dir=Path("exports") / "clip",
            audio_path=Path("exports") / "clip" / "speech.wav",
            source_srt_path=Path("exports") / "clip" / "source.srt",
            translated_srt_path=Path("exports") / "clip" / "translated.srt",
            manifest_path=Path("exports") / "clip" / "manifest.json",
            cue_count=1,
            script_text="Xin chao.",
            script_language="vi",
            warnings=[],
        )

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            app.subtitle_draft = Mock(spec=VideoSubtitleDraft)
            app._subtitle_export_revision = 3
            app._subtitle_edit_revision = 4
            app._finish_success(result)

            self.assertTrue(app._subtitle_draft_dirty)
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
            with patch("app.voice.gui.export_subtitle_package", side_effect=OSError("closed")):
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
        with patch("app.voice.gui.prepare_subtitles_from_video", return_value=draft):
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
            with patch("app.voice.gui.prepare_subtitles_from_video", return_value=draft):
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
            with patch("app.voice.tts.EdgeTTS.initial_voices", return_value=[]):
                app = GalaxyStudioApp(root, config_path=self.config_path)
                options = GenerationOptions(text="Hello.", output_dir=Path("exports"), project_name="clip")
                translation_options = AITranslationOptions(
                    source_language="en",
                    target_language="vi",
                    api_key="test-key",
                )

                with patch("app.voice.gui.translate_script_text", return_value="Xin chao.") as translate:
                    with patch("app.voice.gui.generate_package", return_value=result) as generate:
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
            with patch("app.voice.tts.EdgeTTS.initial_voices", return_value=voices):
                app = GalaxyStudioApp(root, config_path=self.config_path)
                app.script_text.insert("1.0", "Hello.")
                app.script_language_code = "en"
                app.voice_name.set("English Voice")
                app.ai_api_key.set("test-key")

                with patch("app.voice.gui.threading.Thread") as thread:
                    app.start_generate()

                generation_options, translation_options, tts_engine = thread.call_args.kwargs["args"]
                self.assertEqual(generation_options.voice_name, "Vietnamese Voice")
                self.assertEqual(translation_options.target_language, "vi")
                self.assertIs(tts_engine, app.tts)
                thread.return_value.start.assert_called_once()
        finally:
            root.destroy()

    def test_manual_script_uses_selected_source_language_for_translation(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        voices = [
            Voice(name="Vietnamese Voice", culture="vi-VN", gender="Female", age="Adult"),
        ]

        try:
            with patch("app.voice.tts.EdgeTTS.initial_voices", return_value=voices):
                app = GalaxyStudioApp(root, config_path=self.config_path)
                app.script_text.insert("1.0", "Hello.")
                app.video_source_language.set("English")
                app.video_target_language.set("Vietnamese")
                app.ai_api_key.set("test-key")

                with patch("app.voice.gui.threading.Thread") as thread:
                    app.start_generate()

                _generation_options, translation_options, _tts_engine = thread.call_args.kwargs["args"]
                self.assertEqual(translation_options.source_language, "en")
                self.assertEqual(translation_options.target_language, "vi")
                thread.return_value.start.assert_called_once()
        finally:
            root.destroy()

    def test_start_generate_waits_when_target_voice_is_not_loaded(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        vietnamese_voices = [
            Voice(name="Vietnamese Voice", culture="vi-VN", gender="Female", age="Adult"),
        ]

        try:
            with patch("app.voice.tts.EdgeTTS.initial_voices", return_value=vietnamese_voices):
                app = GalaxyStudioApp(root, config_path=self.config_path)
                app.script_text.insert("1.0", "Hello.")
                app.script_language_code = "en"
                app.video_target_language.set("Japanese")
                app.ai_api_key.set("test-key")

                with (
                    patch.object(app, "refresh_voices") as refresh,
                    patch("app.voice.gui.messagebox.showwarning") as warning,
                    patch("app.voice.gui.threading.Thread") as thread,
                ):
                    app.start_generate()

                refresh.assert_called_once()
                warning.assert_called_once()
                thread.assert_not_called()
        finally:
            root.destroy()

    def test_start_generate_without_translation_still_requires_a_matching_voice(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        vietnamese_voices = [
            Voice(name="Vietnamese Voice", culture="vi-VN", gender="Female", age="Adult"),
        ]

        try:
            with patch("app.voice.tts.EdgeTTS.initial_voices", return_value=vietnamese_voices):
                app = GalaxyStudioApp(root, config_path=self.config_path)
                app.script_text.insert("1.0", "こんにちは")
                app.script_language_code = "ja"
                app.video_target_language.set("Japanese")

                with (
                    patch.object(app, "refresh_voices") as refresh,
                    patch("app.voice.gui.messagebox.showwarning") as warning,
                    patch("app.voice.gui.threading.Thread") as thread,
                ):
                    app.start_generate()

                refresh.assert_called_once()
                warning.assert_called_once()
                thread.assert_not_called()
        finally:
            root.destroy()

    def test_refresh_voices_runs_outside_the_tk_thread(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            app = GalaxyStudioApp(root, config_path=self.config_path)
            with patch("app.voice.gui.threading.Thread") as thread:
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
