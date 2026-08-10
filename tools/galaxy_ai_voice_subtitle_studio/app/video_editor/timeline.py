from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from ..voice.srt import SubtitleCue


TRACK_LABEL_WIDTH = 92
RULER_HEIGHT = 28
MIN_TRACK_HEIGHT = 36
MAX_TRACK_HEIGHT = 120
HANDLE_WIDTH = 7


class EditorTimeline(ttk.Frame):
    """Compact three-track timeline with draggable subtitle cues and audio offset."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_seek: Callable[[int], None] | None = None,
        on_select_cue: Callable[[int], None] | None = None,
        on_change_cue: Callable[[int, int, int], None] | None = None,
        on_audio_offset: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.on_seek = on_seek
        self.on_select_cue = on_select_cue
        self.on_change_cue = on_change_cue
        self.on_audio_offset = on_audio_offset

        self.duration_ms = 1
        self.playhead_ms = 0
        self.pixels_per_second = 80.0
        self.cues: list[SubtitleCue] = []
        self.video_label = ""
        self.audio_label = ""
        self.audio_duration_ms = 0
        self.audio_offset_ms = 0
        self.selected_cue: int | None = None
        self.track_heights = [48, 48, 60]
        self._drag: dict[str, int | str] | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self,
            bg="#202421",
            height=RULER_HEIGHT + sum(self.track_heights),
            highlightthickness=0,
            xscrollincrement=1,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, orient="horizontal", command=self._scroll_xview)
        self.scrollbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=self.scrollbar.set)

        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)

    def set_project(
        self,
        *,
        duration_ms: int,
        video_label: str,
        audio_label: str = "",
        audio_duration_ms: int = 0,
        audio_offset_ms: int = 0,
        cues: list[SubtitleCue] | None = None,
    ) -> None:
        self.duration_ms = max(1, int(duration_ms))
        self.video_label = video_label
        self.audio_label = audio_label
        self.audio_duration_ms = max(0, int(audio_duration_ms))
        self.audio_offset_ms = max(0, int(audio_offset_ms))
        self.cues = list(cues or [])
        self.playhead_ms = min(self.playhead_ms, self.duration_ms)
        self.redraw()

    def set_cues(self, cues: list[SubtitleCue], selected: int | None = None) -> None:
        self.cues = list(cues)
        self.selected_cue = selected if selected is not None and 0 <= selected < len(cues) else None
        self.redraw()

    def set_audio(self, label: str, duration_ms: int, offset_ms: int = 0) -> None:
        self.audio_label = label
        self.audio_duration_ms = max(0, int(duration_ms))
        self.audio_offset_ms = max(0, int(offset_ms))
        self.redraw()

    def set_playhead(self, milliseconds: int, *, reveal: bool = False) -> None:
        self.playhead_ms = max(0, min(self.duration_ms, int(milliseconds)))
        self._draw_playhead()
        if reveal:
            self._reveal_time(self.playhead_ms)

    def set_zoom(self, pixels_per_second: float) -> None:
        center_ms = self._visible_center_ms()
        self.pixels_per_second = max(0.1, min(300.0, float(pixels_per_second)))
        self.redraw()
        self._reveal_time(center_ms, center=True)

    def drop_time_at(self, root_x: int, root_y: int) -> int | None:
        """Return the timeline position under a screen coordinate, or None outside the tracks."""
        canvas_x = root_x - self.canvas.winfo_rootx()
        canvas_y = root_y - self.canvas.winfo_rooty()
        if not 0 <= canvas_x < self.canvas.winfo_width():
            return None
        if not RULER_HEIGHT <= canvas_y < RULER_HEIGHT + sum(self.track_heights):
            return None
        return self._x_to_time(self.canvas.canvasx(canvas_x))

    def redraw(self) -> None:
        self.canvas.delete("all")
        width = self._content_width()
        height = RULER_HEIGHT + sum(self.track_heights)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self._draw_background(width, height)
        self._draw_ruler(width)
        self._draw_tracks(width)
        self._draw_playhead()

    def _draw_background(self, width: int, height: int) -> None:
        self.canvas.create_rectangle(0, 0, width, height, fill="#202421", outline="")
        self.canvas.create_rectangle(
            0,
            0,
            TRACK_LABEL_WIDTH,
            height,
            fill="#181b19",
            outline="",
            tags=("fixed-label-bg",),
        )

    def _draw_ruler(self, width: int) -> None:
        self.canvas.create_line(0, RULER_HEIGHT, width, RULER_HEIGHT, fill="#4f5753")
        major_seconds = self._major_tick_seconds()
        total_seconds = math.ceil(self.duration_ms / 1000)
        visible_start, visible_end = self._visible_time_range()
        start_seconds = max(0, visible_start // 1000 - major_seconds)
        start_seconds = start_seconds // major_seconds * major_seconds
        end_seconds = min(total_seconds + major_seconds, visible_end // 1000 + major_seconds)
        for seconds in range(start_seconds, end_seconds + 1, major_seconds):
            x = self._time_to_x(seconds * 1000)
            self.canvas.create_line(x, 8, x, RULER_HEIGHT, fill="#75807a")
            self.canvas.create_text(
                x + 4,
                5,
                text=_short_time(seconds),
                fill="#cdd4d0",
                anchor="nw",
                font=("Segoe UI", 8),
            )

    def _draw_tracks(self, width: int) -> None:
        labels = ("Video", "Audio", "Subtitle")
        colors = ("#315f68", "#46634a", "#8a6637")
        y = RULER_HEIGHT
        for index, (label, height, color) in enumerate(zip(labels, self.track_heights, colors)):
            bottom = y + height
            self.canvas.create_rectangle(
                0, y, width, bottom, fill="#252a27", outline="#414844", tags=("track-bg",)
            )
            self.canvas.create_rectangle(
                0, y, TRACK_LABEL_WIDTH, bottom, fill="#181b19", outline="#414844"
            )
            self.canvas.create_text(
                12,
                (y + bottom) / 2,
                text=label,
                fill="#e5e9e7",
                anchor="w",
                font=("Segoe UI Semibold", 9),
            )
            if index < 2:
                self.canvas.create_line(
                    0,
                    bottom,
                    width,
                    bottom,
                    fill="#67716c",
                    width=3,
                    tags=("separator", f"separator-{index}"),
                )
            if index == 0 and self.video_label:
                self._draw_clip(
                    index,
                    0,
                    self.duration_ms,
                    self.video_label,
                    colors[0],
                    ("video-clip",),
                )
            elif index == 1 and self.audio_label:
                end_ms = min(self.duration_ms, self.audio_offset_ms + self.audio_duration_ms)
                if end_ms > self.audio_offset_ms:
                    self._draw_clip(
                        index,
                        self.audio_offset_ms,
                        end_ms,
                        self.audio_label,
                        colors[1],
                        ("audio-clip",),
                    )
            y = bottom

        visible_cues = self._visible_cues()
        if len(visible_cues) > 100:
            self._draw_cue_overview(visible_cues, colors[2])
            return

        for cue_index, cue in visible_cues:
            color = "#d89435" if cue_index == self.selected_cue else colors[2]
            self._draw_clip(
                2,
                cue.start_ms,
                cue.end_ms,
                cue.text.replace("\n", " "),
                color,
                ("cue", f"cue-{cue_index}"),
                handles=True,
            )

    def _draw_cue_overview(
        self,
        visible_cues: list[tuple[int, SubtitleCue]],
        color: str,
    ) -> None:
        top, bottom = self._track_bounds(2)
        y1, y2 = top + 8, bottom - 8
        intervals: list[list[int]] = []
        for _cue_index, cue in visible_cues:
            x1 = math.floor(self._time_to_x(cue.start_ms))
            x2 = max(x1 + 1, math.ceil(self._time_to_x(cue.end_ms)))
            if intervals and x1 <= intervals[-1][1] + 1:
                intervals[-1][1] = max(intervals[-1][1], x2)
            else:
                intervals.append([x1, x2])

        for x1, x2 in intervals:
            self.canvas.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                fill=color,
                outline="",
                tags=("cue-overview",),
            )

        visible_indexes = {index for index, _cue in visible_cues}
        if self.selected_cue is not None and self.selected_cue in visible_indexes:
            cue = self.cues[self.selected_cue]
            x1 = self._time_to_x(cue.start_ms)
            x2 = max(x1 + 2, self._time_to_x(cue.end_ms))
            self.canvas.create_rectangle(
                x1,
                y1 - 2,
                x2,
                y2 + 2,
                fill="#f4c36c",
                outline="#fff1c9",
                tags=("cue-overview-selection",),
            )

    def _draw_clip(
        self,
        track_index: int,
        start_ms: int,
        end_ms: int,
        label: str,
        color: str,
        tags: tuple[str, ...],
        *,
        handles: bool = False,
    ) -> None:
        top, bottom = self._track_bounds(track_index)
        x1 = self._time_to_x(start_ms)
        x2 = max(x1 + 3, self._time_to_x(end_ms))
        y1, y2 = top + 6, bottom - 6
        self.canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="#b7c0bb", tags=tags)
        self.canvas.create_text(
            x1 + 8,
            (y1 + y2) / 2,
            text=label,
            fill="#ffffff",
            anchor="w",
            width=max(1, x2 - x1 - 14),
            font=("Segoe UI", 8),
            tags=tags,
        )
        if handles:
            cue_tag = next(tag for tag in tags if tag.startswith("cue-"))
            self.canvas.create_rectangle(
                x1,
                y1,
                x1 + HANDLE_WIDTH,
                y2,
                fill="#f4c36c",
                outline="",
                tags=("cue-handle", "cue-start", cue_tag),
            )
            self.canvas.create_rectangle(
                x2 - HANDLE_WIDTH,
                y1,
                x2,
                y2,
                fill="#f4c36c",
                outline="",
                tags=("cue-handle", "cue-end", cue_tag),
            )

    def _draw_playhead(self) -> None:
        self.canvas.delete("playhead")
        x = self._time_to_x(self.playhead_ms)
        height = RULER_HEIGHT + sum(self.track_heights)
        self.canvas.create_line(x, 0, x, height, fill="#f05e4f", width=2, tags=("playhead",))
        self.canvas.create_polygon(
            x - 5,
            0,
            x + 5,
            0,
            x,
            8,
            fill="#f05e4f",
            outline="",
            tags=("playhead",),
        )

    def _on_press(self, event: tk.Event) -> None:
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        tags = self._tags_at(x, y)
        separator = next((tag for tag in tags if tag.startswith("separator-")), None)
        if separator:
            self._drag = {
                "kind": "separator",
                "track": int(separator.split("-", 1)[1]),
                "origin_y": round(y),
            }
            return

        cue_tag = next((tag for tag in tags if _is_cue_index_tag(tag)), None)
        if cue_tag:
            cue_index = int(cue_tag.split("-", 1)[1])
            cue = self.cues[cue_index]
            mode = "move"
            if "cue-start" in tags:
                mode = "start"
            elif "cue-end" in tags:
                mode = "end"
            self.selected_cue = cue_index
            self._drag = {
                "kind": "cue",
                "mode": mode,
                "index": cue_index,
                "origin_x": round(x),
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
            }
            if self.on_select_cue:
                self.on_select_cue(cue_index)
            self.redraw()
            return

        if "audio-clip" in tags:
            self._drag = {
                "kind": "audio",
                "origin_x": round(x),
                "offset_ms": self.audio_offset_ms,
            }
            return

        if x >= TRACK_LABEL_WIDTH:
            milliseconds = self._x_to_time(x)
            self.set_playhead(milliseconds)
            if self.on_seek:
                self.on_seek(milliseconds)

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag is None:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        kind = self._drag["kind"]
        if kind == "separator":
            track = int(self._drag["track"])
            origin_y = int(self._drag["origin_y"])
            delta = round(y) - origin_y
            old_height = self.track_heights[track]
            next_height = self.track_heights[track + 1]
            changed = max(MIN_TRACK_HEIGHT, min(MAX_TRACK_HEIGHT, old_height + delta))
            delta = changed - old_height
            if MIN_TRACK_HEIGHT <= next_height - delta <= MAX_TRACK_HEIGHT:
                self.track_heights[track] = changed
                self.track_heights[track + 1] = next_height - delta
                self._drag["origin_y"] = round(y)
                self.redraw()
            return

        delta_ms = self._snap_ms(self._pixels_to_ms(round(x) - int(self._drag["origin_x"])))
        if kind == "audio":
            self.audio_offset_ms = max(0, int(self._drag["offset_ms"]) + delta_ms)
            self.redraw()
            return

        cue_index = int(self._drag["index"])
        start_ms = int(self._drag["start_ms"])
        end_ms = int(self._drag["end_ms"])
        mode = str(self._drag["mode"])
        if mode == "move":
            duration = end_ms - start_ms
            start_ms = max(0, min(self.duration_ms - duration, start_ms + delta_ms))
            end_ms = start_ms + duration
        elif mode == "start":
            start_ms = max(0, min(end_ms - 100, start_ms + delta_ms))
        else:
            end_ms = min(self.duration_ms, max(start_ms + 100, end_ms + delta_ms))
        cue = self.cues[cue_index]
        self.cues[cue_index] = SubtitleCue(cue.index, start_ms, end_ms, cue.text)
        self.redraw()

    def _on_release(self, _event: tk.Event) -> None:
        if self._drag is None:
            return
        kind = self._drag["kind"]
        if kind == "cue" and self.on_change_cue:
            cue_index = int(self._drag["index"])
            cue = self.cues[cue_index]
            self.on_change_cue(cue_index, cue.start_ms, cue.end_ms)
        elif kind == "audio" and self.on_audio_offset:
            self.on_audio_offset(self.audio_offset_ms)
        self._drag = None

    def _on_mousewheel(self, event: tk.Event) -> str:
        steps = int(-event.delta / 120)
        self.canvas.xview_scroll(steps * 80, "units")
        self.redraw()
        return "break"

    def _on_configure(self, _event: tk.Event) -> None:
        self.redraw()

    def _scroll_xview(self, *args: str) -> None:
        self.canvas.xview(*args)
        self.redraw()

    def _tags_at(self, x: float, y: float) -> tuple[str, ...]:
        items = self.canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2)
        tags: list[str] = []
        for item in items:
            tags.extend(self.canvas.gettags(item))
        return tuple(tags)

    def _content_width(self) -> int:
        visible = max(500, self.canvas.winfo_width())
        track = TRACK_LABEL_WIDTH + math.ceil(self.duration_ms / 1000 * self.pixels_per_second) + 80
        return max(visible, track)

    def _track_bounds(self, track_index: int) -> tuple[int, int]:
        top = RULER_HEIGHT + sum(self.track_heights[:track_index])
        return top, top + self.track_heights[track_index]

    def _time_to_x(self, milliseconds: int) -> float:
        return TRACK_LABEL_WIDTH + milliseconds / 1000 * self.pixels_per_second

    def _x_to_time(self, x: float) -> int:
        milliseconds = round((x - TRACK_LABEL_WIDTH) * 1000 / self.pixels_per_second)
        return max(0, min(self.duration_ms, milliseconds))

    def _pixels_to_ms(self, pixels: int) -> int:
        return round(pixels * 1000 / self.pixels_per_second)

    @staticmethod
    def _snap_ms(milliseconds: int) -> int:
        return round(milliseconds / 100) * 100

    def _major_tick_seconds(self) -> int:
        for seconds in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1_800, 3_600):
            if seconds * self.pixels_per_second >= 80:
                return seconds
        return 3_600

    def _visible_center_ms(self) -> int:
        left = self.canvas.canvasx(0)
        right = self.canvas.canvasx(self.canvas.winfo_width())
        return self._x_to_time((left + right) / 2)

    def _reveal_time(self, milliseconds: int, *, center: bool = False) -> None:
        width = self._content_width()
        visible = max(1, self.canvas.winfo_width())
        x = self._time_to_x(milliseconds)
        left = self.canvas.canvasx(0)
        right = left + visible
        if center or x < left or x > right:
            target = max(0.0, min(1.0, (x - visible / 2) / max(1, width - visible)))
            self.canvas.xview_moveto(target)
            self.redraw()

    def _visible_cues(self) -> list[tuple[int, SubtitleCue]]:
        visible_start, visible_end = self._visible_time_range()
        overscan = max(1_000, visible_end - visible_start)
        start_ms = max(0, visible_start - overscan)
        end_ms = min(self.duration_ms, visible_end + overscan)
        return [
            (index, cue)
            for index, cue in enumerate(self.cues)
            if cue.end_ms >= start_ms and cue.start_ms <= end_ms
        ]

    def _visible_time_range(self) -> tuple[int, int]:
        left_x = self.canvas.canvasx(0)
        right_x = self.canvas.canvasx(max(1, self.canvas.winfo_width()))
        return self._x_to_time(left_x), self._x_to_time(right_x)


def _short_time(seconds: int) -> str:
    minutes, remaining = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{remaining:02}" if hours else f"{minutes}:{remaining:02}"


def _is_cue_index_tag(tag: str) -> bool:
    return tag.startswith("cue-") and tag[4:].isdigit()
