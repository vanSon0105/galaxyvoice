from __future__ import annotations

import tkinter as tk
import unittest

from app.video_editor.timeline import EditorTimeline
from app.voice.srt import SubtitleCue


class EditorTimelinePerformanceTests(unittest.TestCase):
    def test_long_subtitle_track_only_materializes_visible_cues(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")

        try:
            root.geometry("900x300")
            timeline = EditorTimeline(root)
            timeline.pack(fill="both", expand=True)
            cues = [
                SubtitleCue(index + 1, index * 2_000, index * 2_000 + 1_600, f"Cue {index + 1}")
                for index in range(1_260)
            ]

            timeline.set_project(
                duration_ms=42 * 60 * 1_000,
                video_label="long-video.mp4",
                cues=cues,
            )
            root.update_idletasks()
            root.update()

            materialized_cue_items = timeline.canvas.find_withtag("cue")
            self.assertLessEqual(len(materialized_cue_items), 300)
            self.assertLessEqual(len(timeline.canvas.find_all()), 300)

            timeline._scroll_xview("moveto", "0.5")
            root.update_idletasks()

            middle_cue_items = timeline.canvas.find_withtag("cue-631")
            self.assertTrue(middle_cue_items)
            self.assertFalse(timeline.canvas.find_withtag("cue-1"))

            timeline.set_zoom(0.01)
            root.update_idletasks()
            self.assertEqual(timeline.pixels_per_second, 0.1)
            self.assertEqual(timeline._major_tick_seconds(), 900)
            self.assertTrue(timeline.canvas.find_withtag("cue-overview"))
            self.assertLessEqual(len(timeline.canvas.find_all()), 300)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
