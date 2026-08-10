from __future__ import annotations

import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..common.compute import PROCESSING_DEVICE_LABELS, processing_device_code
from ..common.ffmpeg import find_ffmpeg, find_ffplay
from . import propainter
from .constants import (
    PREVIEW_FPS,
    PREVIEW_HEIGHT,
    PREVIEW_WIDTH,
    REMOVAL_MODE_CODES,
    REMOVAL_MODE_LABELS,
)
from .service import (
    AI_INPAINT_MODES,
    BLUR_MODE,
    STRIP_MODE,
    SubtitleRemovalOptions,
    build_audio_playback_command,
    build_playback_command,
    create_video_preview,
    probe_video_duration,
    remove_subtitles_from_video,
)


class SubtitleRemovalTabMixin:
    def _build_removal_tab(self) -> None:
        self.removal_tab = ttk.Frame(self.main_notebook, padding=(0, 10, 0, 0))
        self.removal_tab.columnconfigure(0, weight=1)
        self.removal_tab.columnconfigure(1, minsize=340)
        self.removal_tab.rowconfigure(0, weight=1)
        self.main_notebook.add(self.removal_tab, text="Xóa phụ đề")

        preview_panel = ttk.Frame(self.removal_tab)
        preview_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(1, weight=1)
        ttk.Label(preview_panel, text="Xem trước", style="PageSection.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )

        preview_holder = ttk.Frame(preview_panel)
        preview_holder.grid(row=1, column=0, sticky="nsew")
        preview_holder.columnconfigure(0, weight=1)
        preview_holder.rowconfigure(0, weight=1)
        self.removal_preview_canvas = tk.Canvas(
            preview_holder,
            width=PREVIEW_WIDTH,
            height=PREVIEW_HEIGHT,
            bg="#161a18",
            highlightthickness=1,
            highlightbackground="#a8a59e",
            cursor="crosshair",
        )
        self.removal_preview_canvas.grid(row=0, column=0, sticky="n")
        self.removal_preview_canvas.create_text(
            PREVIEW_WIDTH // 2,
            PREVIEW_HEIGHT // 2,
            text="Chọn video để xem trước",
            fill="#d7ddd9",
            font=("Segoe UI", 11),
            tags=("preview-placeholder",),
        )
        self.removal_preview_canvas.bind("<ButtonPress-1>", self._start_removal_region_drag)
        self.removal_preview_canvas.bind("<B1-Motion>", self._drag_removal_region)
        self.removal_preview_canvas.bind("<ButtonRelease-1>", self._finish_removal_region_drag)
        self.removal_region_rectangle = self.removal_preview_canvas.create_rectangle(
            0,
            0,
            0,
            0,
            outline="#f1b847",
            width=3,
            fill="#f1b847",
            stipple="gray50",
        )
        self._draw_removal_region()

        transport = ttk.Frame(preview_panel)
        transport.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        transport.columnconfigure(1, weight=1)
        self.removal_play_button = ttk.Button(
            transport,
            text="Phát",
            command=self.toggle_removal_playback,
            state="disabled",
            width=10,
        )
        self.removal_play_button.grid(row=0, column=0, padx=(0, 8))
        self.removal_timeline = ttk.Scale(
            transport,
            from_=0,
            to=1,
            variable=self.removal_timeline_position,
            orient="horizontal",
            state="disabled",
            command=self._on_removal_timeline_changed,
        )
        self.removal_timeline.grid(row=0, column=1, sticky="ew")
        self.removal_timeline.bind("<ButtonPress-1>", self._start_removal_timeline_seek)
        self.removal_timeline.bind("<ButtonRelease-1>", self._finish_removal_timeline_seek)
        ttk.Label(
            transport,
            textvariable=self.removal_time_text,
            width=14,
            anchor="e",
        ).grid(row=0, column=2, padx=(8, 0))

        controls_panel = ttk.Frame(self.removal_tab, style="Panel.TFrame", padding=14)
        controls_panel.grid(row=0, column=1, sticky="nsew")
        controls_panel.configure(width=360)
        controls_panel.grid_propagate(False)
        controls_panel.columnconfigure(0, weight=1)
        controls_panel.rowconfigure(0, weight=1)
        controls = self._build_scrollable_controls(controls_panel)

        ttk.Label(controls, text="Video đầu vào", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        input_row = ttk.Frame(controls, style="Surface.TFrame")
        input_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        input_row.columnconfigure(0, weight=1)
        ttk.Entry(input_row, textvariable=self.removal_video_path).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(input_row, text="Browse", command=self.browse_removal_video).grid(row=0, column=1)

        ttk.Label(controls, text="Tên project", style="Panel.TLabel").grid(
            row=2, column=0, sticky="w", pady=(12, 2)
        )
        ttk.Entry(controls, textvariable=self.removal_project_name).grid(row=3, column=0, sticky="ew")

        ttk.Label(controls, text="Output folder", style="Panel.TLabel").grid(
            row=4, column=0, sticky="w", pady=(12, 2)
        )
        output_row = ttk.Frame(controls, style="Surface.TFrame")
        output_row.grid(row=5, column=0, sticky="ew")
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.output_dir).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(output_row, text="Browse", command=self.browse_output).grid(row=0, column=1)

        ttk.Label(controls, text="Chế độ", style="Panel.TLabel").grid(
            row=6, column=0, sticky="w", pady=(12, 2)
        )
        self.removal_mode_combo = ttk.Combobox(
            controls,
            textvariable=self.removal_mode,
            values=tuple(REMOVAL_MODE_LABELS.values()),
            state="readonly",
        )
        self.removal_mode_combo.grid(row=7, column=0, sticky="ew")
        self.removal_mode_combo.bind("<<ComboboxSelected>>", self._on_removal_mode_changed)

        device_row = ttk.Frame(controls, style="Surface.TFrame")
        device_row.grid(row=8, column=0, sticky="ew", pady=(12, 0))
        device_row.columnconfigure(0, weight=1)
        ttk.Label(device_row, text="Thiết bị xử lý", style="Panel.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 2)
        )
        self.removal_device_combo = ttk.Combobox(
            device_row,
            textvariable=self.removal_processing_device,
            values=tuple(PROCESSING_DEVICE_LABELS.values()),
            state="readonly",
        )
        self.removal_device_combo.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.propainter_install_button = ttk.Button(
            device_row,
            text="Cài ProPainter",
            command=self.install_propainter,
        )
        self.propainter_install_button.grid(row=1, column=1, sticky="e")

        region = ttk.Frame(controls, style="Surface.TFrame")
        region.grid(row=9, column=0, sticky="ew", pady=(14, 0))
        region.columnconfigure(1, weight=1)
        region.columnconfigure(3, weight=1)
        ttk.Label(region, text="Vùng phụ đề (%)", style="Section.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )
        self.removal_region_widgets: list[tk.Widget] = []
        region_fields = (
            ("X", self.subtitle_region_x, 0, 99),
            ("Y", self.subtitle_region_y, 0, 99),
            ("Rộng", self.subtitle_region_width, 1, 100),
            ("Cao", self.subtitle_region_height, 1, 100),
        )
        for index, (label, variable, minimum, maximum) in enumerate(region_fields):
            row = 1 + index // 2
            column = (index % 2) * 2
            ttk.Label(region, text=label, style="Panel.TLabel").grid(
                row=row, column=column, sticky="w", pady=3, padx=(0, 6)
            )
            spinbox = ttk.Spinbox(
                region,
                from_=minimum,
                to=maximum,
                increment=1,
                textvariable=variable,
                width=7,
            )
            spinbox.grid(row=row, column=column + 1, sticky="ew", pady=3, padx=(0, 10))
            self.removal_region_widgets.append(spinbox)

        blur_row = ttk.Frame(controls, style="Surface.TFrame")
        blur_row.grid(row=10, column=0, sticky="ew", pady=(12, 0))
        blur_row.columnconfigure(1, weight=1)
        ttk.Label(blur_row, text="Độ mờ", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.removal_blur_scale = ttk.Scale(
            blur_row,
            from_=1,
            to=50,
            variable=self.subtitle_blur_strength,
            orient="horizontal",
        )
        self.removal_blur_scale.grid(row=0, column=1, sticky="ew", padx=8)
        self.removal_region_widgets.append(self.removal_blur_scale)
        ttk.Label(
            blur_row,
            textvariable=self.subtitle_blur_strength,
            style="Panel.TLabel",
            width=4,
            anchor="e",
        ).grid(row=0, column=2, sticky="e")

        action_row = ttk.Frame(controls, style="Surface.TFrame")
        action_row.grid(row=11, column=0, sticky="ew", pady=(18, 0))
        action_row.columnconfigure(0, weight=1)
        action_row.columnconfigure(1, weight=1)
        self.removal_preview_button = ttk.Button(
            action_row,
            text="Xem trước",
            command=self.start_removal_preview,
        )
        self.removal_preview_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.removal_process_button = ttk.Button(
            action_row,
            text="Xử lý video",
            style="Accent.TButton",
            command=self.start_remove_subtitles,
        )
        self.removal_process_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.removal_open_button = ttk.Button(
            controls,
            text="Open Output",
            command=self.open_output,
            state="disabled",
        )
        self.removal_open_button.grid(row=12, column=0, sticky="ew", pady=(8, 0))
        self.removal_progress = ttk.Progressbar(controls, mode="indeterminate")
        self.removal_progress.grid(row=13, column=0, sticky="ew", pady=(12, 0))
        self._on_removal_mode_changed()

    def browse_removal_video(self) -> None:
        file_path = filedialog.askopenfilename(
            filetypes=[
                ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("All files", "*.*"),
            ]
        )
        if not file_path:
            return

        self._stop_removal_playback()
        self.removal_video_path.set(file_path)
        self.removal_project_name.set(f"{Path(file_path).stem}-clean")
        self.removal_duration_seconds = 0.0
        self.removal_timeline_position.set(0.0)
        self.removal_time_text.set("00:00 / 00:00")
        self.removal_play_button.configure(state="disabled")
        self.removal_timeline.configure(state="disabled", to=1)
        self.start_removal_preview()

    def _on_removal_mode_changed(self, _event: tk.Event | None = None) -> None:
        mode = self._removal_mode_code()
        region_state = "disabled" if mode == STRIP_MODE else "normal"
        for widget in self.removal_region_widgets[:-1]:
            widget.configure(state=region_state)
        self.removal_blur_scale.configure(state="normal" if mode == BLUR_MODE else "disabled")
        if hasattr(self, "propainter_install_button"):
            busy = bool(self.worker and self.worker.is_alive())
            ai_ready = mode in AI_INPAINT_MODES and not busy
            self.removal_device_combo.configure(state="readonly" if ai_ready else "disabled")
            install_state = "normal" if ai_ready else "disabled"
            self.propainter_install_button.configure(state=install_state)
        self._draw_removal_region()

    def _removal_mode_code(self) -> str:
        return REMOVAL_MODE_CODES.get(self.removal_mode.get(), BLUR_MODE)

    def _draw_removal_region(self, *_args: str) -> None:
        if not hasattr(self, "removal_preview_canvas"):
            return
        if self._removal_mode_code() == STRIP_MODE:
            self.removal_preview_canvas.itemconfigure(self.removal_region_rectangle, state="hidden")
            return

        x = self._config_int(self.subtitle_region_x, 5, 0, 99)
        y = self._config_int(self.subtitle_region_y, 75, 0, 99)
        width = min(self._config_int(self.subtitle_region_width, 90, 1, 100), 100 - x)
        height = min(self._config_int(self.subtitle_region_height, 20, 1, 100), 100 - y)
        self.removal_preview_canvas.coords(
            self.removal_region_rectangle,
            x * PREVIEW_WIDTH / 100,
            y * PREVIEW_HEIGHT / 100,
            (x + width) * PREVIEW_WIDTH / 100,
            (y + height) * PREVIEW_HEIGHT / 100,
        )
        self.removal_preview_canvas.itemconfigure(self.removal_region_rectangle, state="normal")
        self.removal_preview_canvas.tag_raise(self.removal_region_rectangle)

    def _start_removal_region_drag(self, event: tk.Event) -> None:
        if self._removal_mode_code() == STRIP_MODE:
            return
        self._removal_drag_start = (
            max(0, min(PREVIEW_WIDTH, int(event.x))),
            max(0, min(PREVIEW_HEIGHT, int(event.y))),
        )

    def _drag_removal_region(self, event: tk.Event) -> None:
        if self._removal_drag_start is None:
            return
        start_x, start_y = self._removal_drag_start
        current_x = max(0, min(PREVIEW_WIDTH, int(event.x)))
        current_y = max(0, min(PREVIEW_HEIGHT, int(event.y)))
        self.removal_preview_canvas.coords(
            self.removal_region_rectangle,
            min(start_x, current_x),
            min(start_y, current_y),
            max(start_x, current_x),
            max(start_y, current_y),
        )

    def _finish_removal_region_drag(self, event: tk.Event) -> None:
        if self._removal_drag_start is None:
            return
        start_x, start_y = self._removal_drag_start
        self._removal_drag_start = None
        end_x = max(0, min(PREVIEW_WIDTH, int(event.x)))
        end_y = max(0, min(PREVIEW_HEIGHT, int(event.y)))
        left, right = sorted((start_x, end_x))
        top, bottom = sorted((start_y, end_y))
        if right - left < 4 or bottom - top < 4:
            self._draw_removal_region()
            return

        region_x = min(99, round(left * 100 / PREVIEW_WIDTH))
        region_y = min(99, round(top * 100 / PREVIEW_HEIGHT))
        region_width = max(1, min(100 - region_x, round((right - left) * 100 / PREVIEW_WIDTH)))
        region_height = max(1, min(100 - region_y, round((bottom - top) * 100 / PREVIEW_HEIGHT)))
        self.subtitle_region_x.set(region_x)
        self.subtitle_region_y.set(region_y)
        self.subtitle_region_width.set(region_width)
        self.subtitle_region_height.set(region_height)
        self._draw_removal_region()

    def start_removal_preview(self, timestamp_seconds: float | None = None) -> None:
        if (
            self.worker
            and self.worker.is_alive()
            and self.worker is not self._removal_preview_worker
        ):
            return
        video = self.removal_video_path.get().strip()
        if not video:
            messagebox.showwarning("Missing video", "Choose a video before loading a preview.")
            return

        self._stop_removal_playback()
        self._removal_preview_session += 1
        session = self._removal_preview_session
        timestamp = max(0.0, float(timestamp_seconds or 0.0))
        preview_path = Path(self._preview_temp_dir.name) / f"preview-{session}.png"
        self._set_busy(True)
        self.removal_progress.start(12)
        self.status.set("Loading preview")
        self._append_log("Loading video preview...")
        preview_worker = threading.Thread(
            target=self._run_removal_preview,
            args=(session, Path(video).expanduser(), preview_path, timestamp),
            daemon=True,
        )
        self._removal_preview_worker = preview_worker
        self.worker = preview_worker
        preview_worker.start()

    def _run_removal_preview(
        self,
        session: int,
        video_path: Path,
        preview_path: Path,
        timestamp_seconds: float,
    ) -> None:
        try:
            duration = probe_video_duration(video_path)
            timestamp = min(timestamp_seconds, max(0.0, duration - 0.001))
            result = create_video_preview(
                video_path,
                preview_path,
                timestamp_seconds=timestamp,
            )
            self.events.put(
                (
                    "removal_preview_ready",
                    (session, str(video_path), result, duration, timestamp),
                )
            )
        except Exception as error:  # pragma: no cover - UI boundary
            self.events.put(("removal_preview_error", (session, str(video_path), error)))

    def _load_removal_preview(
        self,
        preview_path: Path,
        duration_seconds: float,
        position_seconds: float,
    ) -> None:
        self._removal_preview_image = tk.PhotoImage(file=str(preview_path))
        self._show_removal_preview_image(self._removal_preview_image)
        self.removal_duration_seconds = duration_seconds
        self.removal_timeline.configure(to=max(0.001, duration_seconds), state="normal")
        self.removal_play_button.configure(state="normal")
        self._set_removal_timeline_position(position_seconds)

    def _show_removal_preview_image(self, preview_image: tk.PhotoImage) -> None:
        self.removal_preview_canvas.delete("preview-image")
        self.removal_preview_canvas.delete("preview-placeholder")
        self.removal_preview_canvas.create_image(
            0,
            0,
            image=preview_image,
            anchor="nw",
            tags=("preview-image",),
        )
        self.removal_preview_canvas.tag_lower("preview-image")
        self._draw_removal_region()

    def toggle_removal_playback(self) -> None:
        if self._is_removal_playing():
            self._stop_removal_playback()
            return
        self._start_removal_playback()

    def _start_removal_playback(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        video = self.removal_video_path.get().strip()
        if not video:
            messagebox.showwarning("Missing video", "Choose a video before playing the preview.")
            return
        if self.removal_duration_seconds <= 0:
            self.start_removal_preview()
            return

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            messagebox.showerror("Playback unavailable", "ffmpeg was not found. Run install_ffmpeg.ps1 first.")
            return

        self._stop_removal_playback()
        start_seconds = max(0.0, float(self.removal_timeline_position.get()))
        if start_seconds >= self.removal_duration_seconds - 0.05:
            start_seconds = 0.0
            self._set_removal_timeline_position(0.0)

        session = self._playback_session
        stop_event = threading.Event()
        self._playback_stop = stop_event
        command = build_playback_command(
            ffmpeg,
            Path(video).expanduser(),
            start_seconds=start_seconds,
            width=PREVIEW_WIDTH,
            height=PREVIEW_HEIGHT,
            fps=PREVIEW_FPS,
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as error:
            messagebox.showerror("Playback unavailable", str(error))
            return

        self._playback_process = process
        self._start_removal_audio(Path(video).expanduser(), start_seconds, creationflags)
        self.removal_play_button.configure(text="Tạm dừng")
        self._playback_worker = threading.Thread(
            target=self._read_removal_playback_frames,
            args=(process, stop_event, session, start_seconds),
            daemon=True,
        )
        self._playback_worker.start()

    def _start_removal_audio(self, video_path: Path, start_seconds: float, creationflags: int) -> None:
        ffplay = find_ffplay()
        if not ffplay:
            if not self._ffplay_missing_logged:
                self._append_log("ffplay is not bundled yet; video preview will play without audio.")
                self._ffplay_missing_logged = True
            return
        try:
            self._playback_audio_process = subprocess.Popen(
                build_audio_playback_command(ffplay, video_path, start_seconds=start_seconds),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as error:
            self._append_log(f"Could not start preview audio: {error}")
            self._playback_audio_process = None

    def _read_removal_playback_frames(
        self,
        process: subprocess.Popen[bytes],
        stop_event: threading.Event,
        session: int,
        start_seconds: float,
    ) -> None:
        frame_size = PREVIEW_WIDTH * PREVIEW_HEIGHT * 3
        frame_index = 0
        stdout = process.stdout
        if stdout is None:
            return

        while not stop_event.is_set():
            frame = self._read_exact(stdout, frame_size)
            if len(frame) != frame_size:
                break
            position = min(
                self.removal_duration_seconds,
                start_seconds + frame_index / PREVIEW_FPS,
            )
            frame_index += 1
            self._offer_playback_frame((session, frame, position))

        if stop_event.is_set():
            return

        return_code = process.wait()
        final_position = min(
            self.removal_duration_seconds,
            start_seconds + frame_index / PREVIEW_FPS,
        )
        if return_code:
            stderr = process.stderr.read() if process.stderr is not None else b""
            detail = stderr.decode("utf-8", errors="replace").strip()
            message = detail or f"ffmpeg exited with code {return_code}."
            self.events.put(("removal_playback_error", (session, message)))
            return
        self.events.put(("removal_playback_ended", (session, final_position)))

    @staticmethod
    def _read_exact(stream: object, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = stream.read(remaining)  # type: ignore[attr-defined]
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _offer_playback_frame(self, frame: tuple[int, bytes, float]) -> None:
        try:
            self._playback_frames.put_nowait(frame)
        except queue.Full:
            try:
                self._playback_frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._playback_frames.put_nowait(frame)
            except queue.Full:
                pass

    def _render_latest_playback_frame(self) -> None:
        latest: tuple[int, bytes, float] | None = None
        while True:
            try:
                latest = self._playback_frames.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return

        session, frame, position = latest
        if session != self._playback_session:
            return
        ppm_header = f"P6\n{PREVIEW_WIDTH} {PREVIEW_HEIGHT}\n255\n".encode("ascii")
        self._removal_preview_image = tk.PhotoImage(data=ppm_header + frame, format="PPM")
        self._show_removal_preview_image(self._removal_preview_image)
        if not self._timeline_dragging:
            self._set_removal_timeline_position(position)

    def _stop_removal_playback(self, *, update_ui: bool = True) -> None:
        self._playback_session += 1
        self._playback_stop.set()
        processes = tuple(
            process
            for process in (self._playback_process, self._playback_audio_process)
            if process is not None
        )
        for process in processes:
            if process.poll() is not None:
                continue
            try:
                process.terminate()
            except OSError:
                pass
        self._playback_process = None
        self._playback_audio_process = None
        self._playback_worker = None
        if processes:
            threading.Thread(
                target=self._reap_playback_processes,
                args=(processes,),
                daemon=True,
            ).start()
        while True:
            try:
                self._playback_frames.get_nowait()
            except queue.Empty:
                break
        if update_ui:
            try:
                self.removal_play_button.configure(text="Phát")
            except tk.TclError:
                pass

    @staticmethod
    def _reap_playback_processes(processes: tuple[subprocess.Popen[bytes], ...]) -> None:
        for process in processes:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=0.5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            except OSError:
                pass

            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def _is_removal_playing(self) -> bool:
        return self._playback_process is not None and self._playback_process.poll() is None

    def _on_removal_timeline_changed(self, value: str) -> None:
        try:
            position = float(value)
        except ValueError:
            return
        self._update_removal_time_text(position)

    def _start_removal_timeline_seek(self, _event: tk.Event) -> None:
        self._timeline_dragging = True
        self._resume_after_timeline_seek = self._is_removal_playing()
        if self._resume_after_timeline_seek:
            self._stop_removal_playback()

    def _finish_removal_timeline_seek(self, _event: tk.Event) -> None:
        self._timeline_dragging = False
        position = max(
            0.0,
            min(self.removal_duration_seconds, float(self.removal_timeline_position.get())),
        )
        self._set_removal_timeline_position(position)
        if self._resume_after_timeline_seek:
            self._resume_after_timeline_seek = False
            self._start_removal_playback()
        else:
            self.start_removal_preview(position)

    def _set_removal_timeline_position(self, position_seconds: float) -> None:
        position = max(0.0, min(self.removal_duration_seconds, position_seconds))
        self.removal_timeline_position.set(position)
        self._update_removal_time_text(position)

    def _update_removal_time_text(self, position_seconds: float) -> None:
        self.removal_time_text.set(
            f"{self._format_playback_time(position_seconds)} / "
            f"{self._format_playback_time(self.removal_duration_seconds)}"
        )

    @staticmethod
    def _format_playback_time(seconds: float) -> str:
        total_seconds = max(0, int(seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours:02}:{minutes:02}:{secs:02}"
        return f"{minutes:02}:{secs:02}"

    def _confirm_propainter_license(self) -> bool:
        if self.propainter_license_accepted.get():
            return True
        accepted = messagebox.askyesno(
            "Giấy phép ProPainter",
            "ProPainter chỉ được cấp phép cho mục đích phi thương mại theo NTU S-Lab License 1.0. "
            "Bạn xác nhận chỉ sử dụng chế độ này trong phạm vi giấy phép?",
        )
        if accepted:
            self.propainter_license_accepted.set(True)
        return accepted

    def install_propainter(self) -> None:
        if not self._confirm_propainter_license():
            return
        installer = Path(__file__).resolve().parents[1] / "install_propainter.ps1"
        if not installer.is_file():
            messagebox.showerror("Installer missing", f"Could not find: {installer}")
            return
        device = processing_device_code(self.removal_processing_device.get())
        command = [
            "powershell",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(installer),
            "-AcceptNonCommercialLicense",
            "-Device",
            device,
        ]
        try:
            subprocess.Popen(
                command,
                cwd=installer.parent,
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError as error:
            messagebox.showerror("Could not start installer", str(error))
            return
        self._append_log("Opened the ProPainter installer in a separate window.")

    def start_remove_subtitles(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self._stop_removal_playback()
        video = self.removal_video_path.get().strip()
        if not video:
            messagebox.showwarning("Missing video", "Choose a video before processing.")
            return
        mode = self._removal_mode_code()
        if mode in AI_INPAINT_MODES:
            if not self._confirm_propainter_license():
                return
            try:
                propainter.resolve_propainter_runtime()
            except RuntimeError:
                install_now = messagebox.askyesno(
                    "ProPainter chưa được cài",
                    "Chế độ AI cần cài ProPainter trước khi xử lý video. "
                    "Mở bộ cài ProPainter ngay?\n\n"
                    "Sau khi cửa sổ cài đặt báo ProPainter is ready, hãy bấm Xử lý video lại.",
                )
                if install_now:
                    self.install_propainter()
                return

        region_x = self._config_int(self.subtitle_region_x, 5, 0, 99)
        region_y = self._config_int(self.subtitle_region_y, 75, 0, 99)
        region_width = min(
            self._config_int(self.subtitle_region_width, 90, 1, 100),
            100 - region_x,
        )
        region_height = min(
            self._config_int(self.subtitle_region_height, 20, 1, 100),
            100 - region_y,
        )
        options = SubtitleRemovalOptions(
            video_path=Path(video).expanduser(),
            output_dir=Path(self.output_dir.get()).expanduser(),
            project_name=self.removal_project_name.get(),
            mode=mode,
            region_x=region_x,
            region_y=region_y,
            region_width=region_width,
            region_height=region_height,
            blur_strength=self._config_int(self.subtitle_blur_strength, 18, 1, 100),
            processing_device=processing_device_code(self.removal_processing_device.get()),
        )

        self.last_result = None
        self.open_button.configure(state="disabled")
        self.removal_open_button.configure(state="disabled")
        self._set_busy(True)
        self.removal_progress.start(12)
        self.status.set("Removing subtitles")
        self._append_log("Starting subtitle removal...")
        self.worker = threading.Thread(
            target=self._run_subtitle_removal,
            args=(options,),
            daemon=True,
        )
        self.worker.start()

    def _run_subtitle_removal(self, options: SubtitleRemovalOptions) -> None:
        try:
            result = remove_subtitles_from_video(
                options,
                progress=lambda message: self.events.put(("log", message)),
            )
            self.events.put(("done", result))
        except Exception as error:  # pragma: no cover - UI boundary
            self.events.put(("error", error))
