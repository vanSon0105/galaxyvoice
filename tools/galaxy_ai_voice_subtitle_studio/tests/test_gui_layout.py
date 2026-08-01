from __future__ import annotations

import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.gui import GalaxyStudioApp  # noqa: E402
from app.engine import GenerationOptions, GenerationResult  # noqa: E402
from app.transcription import VideoSubtitleResult  # noqa: E402
from app.translator import AITranslationOptions  # noqa: E402
from app.tts import EDGE_ENGINE_LABEL, EdgeTTS, Voice  # noqa: E402


class GuiLayoutTests(unittest.TestCase):
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
                app = GalaxyStudioApp(root)

            self.assertEqual(app.tts_engine_name.get(), EDGE_ENGINE_LABEL)
            self.assertIsInstance(app.tts, EdgeTTS)
            self.assertEqual(app.voice_name.get(), "vi-VN-HoaiMyNeural")
        finally:
            root.destroy()

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
                app = GalaxyStudioApp(root)
                result = VideoSubtitleResult(
                    project_dir=Path("exports") / "clip",
                    audio_path=Path("exports") / "clip" / "clip_speech.wav",
                    source_srt_path=Path("exports") / "clip" / "clip_original.srt",
                    translated_srt_path=Path("exports") / "clip" / "clip_vi.srt",
                    manifest_path=Path("exports") / "clip" / "subtitle_manifest.json",
                    cue_count=2,
                    script_text="Xin chao.\nThe gioi.",
                    script_language="vi",
                    warnings=[],
                )

                app._finish_success(result)

                self.assertEqual(app.script_text.get("1.0", "end").strip(), "Xin chao.\nThe gioi.")
                self.assertEqual(app.voice_name.get(), "Vietnamese Voice")
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
                app = GalaxyStudioApp(root)
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
                app = GalaxyStudioApp(root)
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
            app = GalaxyStudioApp(root)
            with patch("app.gui.threading.Thread") as thread:
                app.refresh_voices()

            self.assertEqual(thread.call_args.kwargs["target"], app._run_voice_refresh)
            self.assertEqual(thread.call_args.kwargs["args"], (app.tts,))
            thread.return_value.start.assert_called_once()
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
