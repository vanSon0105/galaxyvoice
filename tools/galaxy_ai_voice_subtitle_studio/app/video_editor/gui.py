from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..common.ffmpeg import find_ffmpeg, find_ffplay
from ..common.processes import managed_media_processes
from ..common.theme import PALETTE, text_widget_options
from ..voice.srt import SubtitleCue, render_srt
from .media_bin import EditorMediaBin
from .model import (
    AUDIO_ASSET,
    SUBTITLE_ASSET,
    VIDEO_ASSET,
    EditorAsset,
    fit_cues_to_duration,
    format_timecode,
    normalize_cues,
    parse_timecode,
    update_cue,
)
from .service import (
    AUDIO_MODE_LABELS,
    AUTO_ENCODER,
    CPU_ENCODER,
    ENCODER_LABELS,
    FPS_LABELS,
    INTEL_ENCODER,
    MIX_AUDIO,
    NVIDIA_ENCODER,
    ORIGINAL_RESOLUTION,
    REPLACE_AUDIO,
    RESOLUTION_LABELS,
    SOURCE_FPS,
    EditorExportOptions,
    EditorExportResult,
    EditorMediaInfo,
    build_editor_audio_preview_commands,
    build_editor_frame_command,
    build_editor_preview_command,
    export_editor_video,
    load_editor_subtitles,
    probe_audio_duration,
    probe_editor_media,
)
from .timeline import EditorTimeline


EDITOR_PREVIEW_WIDTH = 384
EDITOR_PREVIEW_HEIGHT = 216
EDITOR_PREVIEW_FPS = 15

# Label tables moved to service.py (shared with the web settings API).


class VideoEditorTabMixin:
    def _build_video_editor_tab(self) -> None:
        self.editor_tab = ttk.Frame(self.main_notebook, padding=(4, 0))
        self.editor_tab.columnconfigure(0, weight=1)
        self.editor_tab.rowconfigure(1, weight=1)
        self.main_notebook.add(self.editor_tab, text="Dựng video")

        toolbar = ttk.Frame(self.editor_tab, style="Toolbar.TFrame", padding=(8, 0))
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.editor_video_button = ttk.Button(
            toolbar,
            text="Thêm video",
            style="Accent.TButton",
            command=self.browse_editor_video,
        )
        self.editor_video_button.grid(row=0, column=0, padx=(0, 6))
        self.editor_audio_button = ttk.Button(
            toolbar,
            text="Thêm audio",
            style="Tool.TButton",
            command=self.browse_editor_audio,
        )
        self.editor_audio_button.grid(row=0, column=1, padx=(0, 6))
        self.editor_subtitle_button = ttk.Button(
            toolbar,
            text="Thêm SRT",
            style="Tool.TButton",
            command=self.browse_editor_subtitle,
        )
        self.editor_subtitle_button.grid(row=0, column=2, padx=(0, 6))
        ttk.Separator(toolbar, orient="vertical").grid(row=0, column=3, sticky="ns", padx=8)
        ttk.Button(
            toolbar,
            text="Xóa audio",
            style="Ghost.TButton",
            command=self.clear_editor_audio,
        ).grid(row=0, column=4, padx=(0, 4))
        ttk.Button(
            toolbar,
            text="Xóa phụ đề",
            style="Ghost.TButton",
            command=self.clear_editor_subtitles,
        ).grid(row=0, column=5)
        ttk.Label(
            toolbar,
            textvariable=self.editor_project_summary,
            style="Toolbar.TLabel",
        ).grid(row=0, column=6, sticky="e", padx=(14, 0))
        toolbar.columnconfigure(6, weight=1)

        self.editor_vertical_pane = ttk.Panedwindow(self.editor_tab, orient="vertical")
        self.editor_vertical_pane.grid(row=1, column=0, sticky="nsew")

        workspace = ttk.Frame(self.editor_vertical_pane)
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=1)
        timeline_panel = ttk.Frame(self.editor_vertical_pane, style="Card.TFrame", padding=4)
        timeline_panel.columnconfigure(0, weight=1)
        timeline_panel.rowconfigure(1, weight=1)
        self.editor_vertical_pane.add(workspace, weight=2)
        self.editor_vertical_pane.add(timeline_panel, weight=2)

        workspace_pane = ttk.Panedwindow(workspace, orient="horizontal")
        workspace_pane.grid(row=0, column=0, sticky="nsew")
        media_panel = ttk.Frame(
            workspace_pane, style="Card.TFrame", padding=12, width=self._px(260)
        )
        preview_panel = ttk.Frame(workspace_pane, style="Card.TFrame", padding=12)
        inspector = ttk.Frame(
            workspace_pane, style="Card.TFrame", padding=10, width=self._px(350)
        )
        media_panel.columnconfigure(0, weight=1)
        media_panel.rowconfigure(0, weight=1)
        media_panel.grid_propagate(False)
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(0, weight=1)
        inspector.columnconfigure(0, weight=1)
        inspector.rowconfigure(0, weight=1)
        inspector.grid_propagate(False)
        workspace_pane.add(media_panel, weight=0)
        workspace_pane.add(preview_panel, weight=3)
        workspace_pane.add(inspector, weight=2)

        self.editor_media_bin = EditorMediaBin(
            media_panel,
            on_drop=self._drop_editor_asset,
            on_activate=self._insert_editor_asset,
            on_remove=self._remove_editor_asset,
        )
        self.editor_media_bin.grid(row=0, column=0, sticky="nsew")

        preview_holder = ttk.Frame(preview_panel, style="Inset.TFrame")
        preview_holder.grid(row=0, column=0, sticky="nsew")
        preview_holder.columnconfigure(0, weight=1)
        preview_holder.rowconfigure(0, weight=1)
        self.editor_preview_canvas = tk.Canvas(
            preview_holder,
            width=EDITOR_PREVIEW_WIDTH,
            height=EDITOR_PREVIEW_HEIGHT,
            bg=PALETTE.preview,
            highlightthickness=1,
            highlightbackground=PALETTE.border,
        )
        self.editor_preview_canvas.grid(row=0, column=0)
        self.editor_preview_canvas.create_text(
            EDITOR_PREVIEW_WIDTH // 2,
            EDITOR_PREVIEW_HEIGHT // 2,
            text="Thêm video để bắt đầu dựng",
            fill=PALETTE.text_muted,
            font="TkTextFont",
            tags=("editor-placeholder",),
        )

        transport = ttk.Frame(preview_panel, style="Transport.TFrame", padding=(10, 8))
        transport.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        transport.columnconfigure(1, weight=1)
        self.editor_play_button = ttk.Button(
            transport,
            text="Phát",
            style="Tool.TButton",
            command=self.toggle_editor_playback,
            state="disabled",
            width=9,
        )
        self.editor_play_button.grid(row=0, column=0, padx=(0, 8))
        self.editor_seek = ttk.Scale(
            transport,
            from_=0,
            to=1,
            variable=self.editor_position,
            orient="horizontal",
            state="disabled",
            command=self._on_editor_seek_changed,
        )
        self.editor_seek.grid(row=0, column=1, sticky="ew")
        self.editor_seek.bind("<ButtonPress-1>", self._start_editor_seek)
        self.editor_seek.bind("<ButtonRelease-1>", self._finish_editor_seek)
        ttk.Label(transport, textvariable=self.editor_time_text, width=16, anchor="e", style="Toolbar.TLabel").grid(
            row=0, column=2, padx=(8, 0)
        )

        self.editor_inspector_notebook = ttk.Notebook(inspector, style="Compact.TNotebook")
        self.editor_inspector_notebook.grid(row=0, column=0, sticky="nsew")
        self._build_editor_subtitle_inspector()
        self._build_editor_export_inspector()

        timeline_toolbar = ttk.Frame(timeline_panel, style="CardHeader.TFrame")
        timeline_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(timeline_toolbar, text="TIMELINE", style="Eyebrow.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(timeline_toolbar, text="Thu phóng", style="CardMuted.TLabel").grid(
            row=0, column=1, padx=(18, 6)
        )
        self.editor_zoom_scale = ttk.Scale(
            timeline_toolbar,
            from_=0.1,
            to=300,
            variable=self.editor_timeline_zoom,
            orient="horizontal",
            command=self._on_editor_zoom,
            length=self._px(180),
        )
        self.editor_zoom_scale.grid(row=0, column=2)
        timeline_toolbar.columnconfigure(3, weight=1)

        self.editor_timeline = EditorTimeline(
            timeline_panel,
            on_seek=self._on_editor_timeline_seek,
            on_select_cue=self._select_editor_cue,
            on_change_cue=self._change_editor_cue_timing,
            on_audio_offset=self._change_editor_audio_offset,
        )
        self.editor_timeline.grid(row=1, column=0, sticky="nsew")

        self.editor_mutable_widgets: list[tk.Widget] = [
            self.editor_video_button,
            self.editor_audio_button,
            self.editor_subtitle_button,
            self.editor_export_button,
            self.editor_resolution_combo,
            self.editor_fps_combo,
            self.editor_encoder_combo,
            self.editor_audio_mode_combo,
            self.editor_media_bin.insert_button,
            self.editor_media_bin.remove_button,
        ]

    def _build_editor_subtitle_inspector(self) -> None:
        tab = ttk.Frame(self.editor_inspector_notebook, style="Card.TFrame", padding=10)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.editor_inspector_notebook.add(tab, text="Phụ đề")

        columns = ("number", "start", "end", "text")
        self.editor_cue_tree = ttk.Treeview(tab, columns=columns, show="headings", height=5, selectmode="browse")
        self.editor_cue_tree.heading("number", text="#")
        self.editor_cue_tree.heading("start", text="Bắt đầu")
        self.editor_cue_tree.heading("end", text="Kết thúc")
        self.editor_cue_tree.heading("text", text="Nội dung")
        self.editor_cue_tree.column(
            "number", width=self._px(36), stretch=False, anchor="center"
        )
        self.editor_cue_tree.column("start", width=self._px(84), stretch=False)
        self.editor_cue_tree.column("end", width=self._px(84), stretch=False)
        self.editor_cue_tree.column("text", width=self._px(180))
        self.editor_cue_tree.grid(row=0, column=0, sticky="nsew")
        cue_scroll = ttk.Scrollbar(tab, orient="vertical", command=self.editor_cue_tree.yview)
        cue_scroll.grid(row=0, column=1, sticky="ns")
        self.editor_cue_tree.configure(yscrollcommand=cue_scroll.set)
        self.editor_cue_tree.bind("<<TreeviewSelect>>", self._on_editor_cue_selected)

        timing = ttk.Frame(tab, style="Card.TFrame")
        timing.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        timing.columnconfigure(1, weight=1)
        timing.columnconfigure(3, weight=1)
        ttk.Label(timing, text="Bắt đầu", style="CardMuted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 5)
        )
        ttk.Entry(timing, textvariable=self.editor_cue_start, width=13).grid(row=0, column=1, sticky="ew")
        ttk.Label(timing, text="Kết thúc", style="CardMuted.TLabel").grid(
            row=0, column=2, sticky="w", padx=(10, 5)
        )
        ttk.Entry(timing, textvariable=self.editor_cue_end, width=13).grid(row=0, column=3, sticky="ew")

        ttk.Label(tab, text="Nội dung", style="CardMuted.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 3)
        )
        self.editor_cue_text = tk.Text(
            tab,
            height=3,
            wrap="word",
            font="TkTextFont",
            padx=8,
            pady=7,
            **text_widget_options(),
        )
        self.editor_cue_text.grid(row=3, column=0, columnspan=2, sticky="ew")

        actions = ttk.Frame(tab, style="Card.TFrame")
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        for column in range(4):
            actions.columnconfigure(column, weight=1)
        ttk.Button(actions, text="Áp dụng", style="Accent.TButton", command=self.apply_editor_cue).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(actions, text="Thêm", style="Tool.TButton", command=self.add_editor_cue).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(actions, text="Xóa", style="Danger.TButton", command=self.delete_editor_cue).grid(
            row=0, column=2, sticky="ew", padx=4
        )
        ttk.Button(actions, text="Căn theo video", style="Tool.TButton", command=self.fit_editor_subtitles).grid(
            row=0, column=3, sticky="ew", padx=(4, 0)
        )

    def _build_editor_export_inspector(self) -> None:
        container = ttk.Frame(self.editor_inspector_notebook, style="Card.TFrame", padding=10)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self.editor_inspector_notebook.add(container, text="Xuất video")
        tab = self._build_scrollable_controls(container)
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text="Tên project").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Entry(tab, textvariable=self.editor_project_name).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(3, 7))
        ttk.Label(tab, text="Thư mục output").grid(row=2, column=0, columnspan=2, sticky="w")
        output = ttk.Frame(tab)
        output.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(3, 8))
        output.columnconfigure(0, weight=1)
        ttk.Entry(output, textvariable=self.editor_output_dir).grid(row=0, column=0, sticky="ew")
        ttk.Button(output, text="Chọn", style="Tool.TButton", command=self.browse_editor_output).grid(
            row=0, column=1, padx=(6, 0)
        )

        ttk.Label(tab, text="Độ phân giải").grid(row=4, column=0, sticky="w")
        ttk.Label(tab, text="Khung hình").grid(row=4, column=1, sticky="w", padx=(8, 0))
        self.editor_resolution_combo = ttk.Combobox(
            tab, textvariable=self.editor_resolution, values=tuple(RESOLUTION_LABELS.values()), state="readonly"
        )
        self.editor_resolution_combo.grid(row=5, column=0, sticky="ew", pady=(3, 8))
        self.editor_fps_combo = ttk.Combobox(
            tab, textvariable=self.editor_fps, values=tuple(FPS_LABELS.values()), state="readonly"
        )
        self.editor_fps_combo.grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(3, 8))

        ttk.Label(tab, text="Bộ mã hóa").grid(row=6, column=0, sticky="w")
        ttk.Label(tab, text="Audio ngoài").grid(row=6, column=1, sticky="w", padx=(8, 0))
        self.editor_encoder_combo = ttk.Combobox(
            tab, textvariable=self.editor_encoder, values=tuple(ENCODER_LABELS.values()), state="readonly"
        )
        self.editor_encoder_combo.grid(row=7, column=0, sticky="ew", pady=(3, 8))
        self.editor_audio_mode_combo = ttk.Combobox(
            tab, textvariable=self.editor_audio_mode, values=tuple(AUDIO_MODE_LABELS.values()), state="readonly"
        )
        self.editor_audio_mode_combo.grid(row=7, column=1, sticky="ew", padx=(8, 0), pady=(3, 8))

        sliders = (
            ("Âm lượng gốc", self.editor_source_volume, 0, 200),
            ("Âm lượng audio", self.editor_external_volume, 0, 200),
            ("Cỡ chữ sub", self.editor_subtitle_font_size, 10, 72),
            ("Lề dưới sub", self.editor_subtitle_margin, 0, 300),
        )
        row = 8
        for label, variable, minimum, maximum in sliders:
            ttk.Label(tab, text=label).grid(row=row, column=0, sticky="w", pady=3)
            control = ttk.Frame(tab)
            control.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=3)
            control.columnconfigure(0, weight=1)
            ttk.Scale(control, from_=minimum, to=maximum, variable=variable, orient="horizontal").grid(
                row=0, column=0, sticky="ew"
            )
            ttk.Label(control, textvariable=variable, width=4, anchor="e").grid(row=0, column=1, padx=(5, 0))
            row += 1

        actions = ttk.Frame(tab)
        actions.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.editor_export_button = ttk.Button(
            actions, text="Xuất video", style="Accent.TButton", command=self.start_editor_export, state="disabled"
        )
        self.editor_export_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.editor_stop_button = ttk.Button(
            actions,
            text="Dừng",
            style="Danger.TButton",
            command=self.stop_editor_export,
            state="disabled",
        )
        self.editor_stop_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.editor_open_button = ttk.Button(
            tab,
            text="Mở thư mục output",
            style="Ghost.TButton",
            command=self.open_editor_output,
            state="disabled",
        )
        self.editor_open_button.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.editor_progress = ttk.Progressbar(tab, mode="determinate", maximum=100)
        self.editor_progress.grid(row=row + 2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def browse_editor_video(self) -> None:
        path = filedialog.askopenfilename(
            title="Chọn video",
            filetypes=[("Video", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v"), ("Tất cả file", "*.*")],
        )
        if not path:
            return
        asset_id = self._editor_asset_id(VIDEO_ASSET, path)
        self.status.set("Đang nhập video...")

        def worker() -> None:
            try:
                info = probe_editor_media(Path(path))
                self.events.put(("editor_video_loaded", (asset_id, path, info)))
            except Exception as error:
                self.events.put(("editor_media_error", (asset_id, error)))

        threading.Thread(target=worker, daemon=True).start()

    def browse_editor_audio(self) -> None:
        path = filedialog.askopenfilename(
            title="Chọn audio",
            filetypes=[("Audio", "*.wav *.mp3 *.flac *.m4a *.aac *.ogg *.opus"), ("Tất cả file", "*.*")],
        )
        if not path:
            return
        asset_id = self._editor_asset_id(AUDIO_ASSET, path)
        self.status.set("Đang nhập audio...")

        def worker() -> None:
            try:
                duration = probe_audio_duration(Path(path))
                self.events.put(("editor_audio_loaded", (asset_id, path, duration)))
            except Exception as error:
                self.events.put(("editor_audio_error", (asset_id, error)))

        threading.Thread(target=worker, daemon=True).start()

    def browse_editor_subtitle(self) -> None:
        path = filedialog.askopenfilename(title="Chọn phụ đề SRT", filetypes=[("SubRip", "*.srt"), ("Tất cả file", "*.*")])
        if not path:
            return
        try:
            cues = load_editor_subtitles(Path(path))
        except Exception as error:
            messagebox.showerror("Không đọc được SRT", str(error))
            return
        asset = EditorAsset(
            asset_id=self._editor_asset_id(SUBTITLE_ASSET, path),
            kind=SUBTITLE_ASSET,
            path=path,
            cues=tuple(cues),
        )
        self._store_editor_asset(asset)
        self.status.set("Đã nhập SRT")
        self._append_log(f"Media Bin: {Path(path).name} ({len(cues)} cue).")

    def import_editor_bundle(
        self,
        video_path: Path,
        audio_path: Path,
        subtitle_path: Path,
    ) -> None:
        """Import and place a dubbing bundle at the beginning of the timeline."""
        video = Path(video_path)
        audio = Path(audio_path)
        subtitle = Path(subtitle_path)
        self.status.set("Đang đưa bản lồng tiếng sang dựng video...")

        def worker() -> None:
            try:
                media_info = probe_editor_media(video)
                audio_duration = probe_audio_duration(audio)
                cues = tuple(load_editor_subtitles(subtitle))
            except Exception as error:
                self.events.put(("editor_bundle_error", error))
            else:
                self.events.put(
                    (
                        "editor_bundle_loaded",
                        (video, media_info, audio, audio_duration, subtitle, cues),
                    )
                )

        threading.Thread(target=worker, daemon=True, name="editor-bundle-import").start()

    def _editor_asset_id(self, kind: str, path: str) -> str:
        normalized = os.path.normcase(os.path.abspath(path))
        for asset in self.editor_assets.values():
            if asset.kind == kind and os.path.normcase(os.path.abspath(asset.path)) == normalized:
                return asset.asset_id
        return f"asset-{uuid.uuid4().hex}"

    def _store_editor_asset(self, asset: EditorAsset) -> None:
        self.editor_assets[asset.asset_id] = asset
        self.editor_media_bin.add_asset(asset)

    def _insert_editor_asset(self, asset_id: str) -> None:
        position_ms = round(float(self.editor_position.get()) * 1000)
        self._activate_editor_asset(asset_id, position_ms)

    def _drop_editor_asset(self, asset_id: str, root_x: int, root_y: int) -> None:
        position_ms = self.editor_timeline.drop_time_at(root_x, root_y)
        if position_ms is not None:
            self._activate_editor_asset(asset_id, position_ms)

    def _activate_editor_asset(self, asset_id: str, position_ms: int) -> None:
        if self.worker and self.worker.is_alive():
            return
        asset = self.editor_assets.get(asset_id)
        if asset is None:
            return
        self._stop_editor_playback()
        if asset.kind == VIDEO_ASSET:
            self.editor_video_path.set(asset.path)
            if not self.editor_project_name.get().strip():
                self.editor_project_name.set(Path(asset.path).stem)
            self._apply_editor_video(
                asset.path,
                EditorMediaInfo(
                    duration_seconds=asset.duration_seconds,
                    width=asset.width,
                    height=asset.height,
                    fps=asset.fps,
                    has_audio=asset.has_audio,
                ),
            )
            return
        if asset.kind == AUDIO_ASSET:
            self.editor_audio_path.set(asset.path)
            self.editor_audio_offset.set(max(0, position_ms))
            self._apply_editor_audio(asset.path, asset.duration_seconds)
            return

        duration_ms = round(self.editor_media_info.duration_seconds * 1000) if self.editor_media_info else None
        self.editor_subtitle_path = Path(asset.path)
        self.editor_cues = normalize_cues(list(asset.cues), duration_ms)
        self._refresh_editor_cues()
        self._sync_editor_timeline()
        self._refresh_editor_preview()
        self._append_log(f"Timeline subtitle: {asset.name} ({len(self.editor_cues)} cue).")

    def _remove_editor_asset(self, asset_id: str) -> None:
        self.editor_assets.pop(asset_id, None)
        self.editor_media_bin.remove_asset(asset_id)

    def browse_editor_output(self) -> None:
        path = filedialog.askdirectory(title="Chọn thư mục output", initialdir=self.editor_output_dir.get() or None)
        if path:
            self.editor_output_dir.set(path)

    def clear_editor_audio(self) -> None:
        self._stop_editor_playback()
        self.editor_audio_path.set("")
        self.editor_audio_duration_seconds = 0.0
        self.editor_audio_offset.set(0)
        self._sync_editor_timeline()

    def clear_editor_subtitles(self) -> None:
        self.editor_cues = []
        self.editor_subtitle_path = None
        self._refresh_editor_cues()
        self._sync_editor_timeline()
        self._refresh_editor_preview()

    def _apply_editor_video(self, path: str, info: EditorMediaInfo) -> None:
        self.editor_media_info = info
        duration_ms = round(info.duration_seconds * 1000)
        self.editor_cues = normalize_cues(self.editor_cues, duration_ms)
        self.editor_seek.configure(to=info.duration_seconds, state="normal")
        self.editor_play_button.configure(state="normal")
        self.editor_export_button.configure(state="normal")
        self.editor_position.set(0.0)
        self._update_editor_time_text(0.0)
        self.editor_project_summary.set(f"{info.width}x{info.height}  |  {info.fps:.2f} fps  |  {self._format_editor_time(info.duration_seconds)}")
        self._refresh_editor_cues()
        self._sync_editor_timeline()
        self._render_editor_still(0.0)
        self._append_log(f"Editor video: {path}")

    def _apply_editor_audio(self, path: str, duration: float) -> None:
        self.editor_audio_duration_seconds = duration
        self._sync_editor_timeline()
        self._append_log(f"Editor audio: {path}")

    def _sync_editor_timeline(self) -> None:
        duration_ms = round(self.editor_media_info.duration_seconds * 1000) if self.editor_media_info else 1
        self.editor_timeline.set_project(
            duration_ms=duration_ms,
            video_label=Path(self.editor_video_path.get()).name if self.editor_video_path.get() else "",
            audio_label=Path(self.editor_audio_path.get()).name if self.editor_audio_path.get() else "",
            audio_duration_ms=round(self.editor_audio_duration_seconds * 1000),
            audio_offset_ms=self._editor_int(self.editor_audio_offset, 0, 0, duration_ms),
            cues=self.editor_cues,
        )

    def _refresh_editor_cues(self, selected: int | None = None) -> None:
        current = selected if selected is not None else self._selected_editor_cue_index()
        self.editor_cue_tree.delete(*self.editor_cue_tree.get_children())
        for index, cue in enumerate(self.editor_cues):
            self.editor_cue_tree.insert(
                "",
                "end",
                iid=f"cue-{index}",
                values=(cue.index, format_timecode(cue.start_ms), format_timecode(cue.end_ms), cue.text.replace("\n", " ")),
            )
        if current is not None and 0 <= current < len(self.editor_cues):
            item = f"cue-{current}"
            self.editor_cue_tree.selection_set(item)
            self.editor_cue_tree.focus(item)
            self.editor_cue_tree.see(item)
            self._load_editor_cue_fields(current)
        elif not self.editor_cues:
            self.editor_cue_start.set("")
            self.editor_cue_end.set("")
            self.editor_cue_text.delete("1.0", "end")

    def _on_editor_cue_selected(self, _event: tk.Event | None = None) -> None:
        index = self._selected_editor_cue_index()
        if index is None:
            return
        self._load_editor_cue_fields(index)
        self.editor_timeline.set_cues(self.editor_cues, index)
        cue = self.editor_cues[index]
        self._set_editor_position(cue.start_ms / 1000, reveal=True)

    def _select_editor_cue(self, index: int) -> None:
        if not 0 <= index < len(self.editor_cues):
            return
        item = f"cue-{index}"
        self.editor_cue_tree.selection_set(item)
        self.editor_cue_tree.focus(item)
        self.editor_cue_tree.see(item)
        self._load_editor_cue_fields(index)

    def _load_editor_cue_fields(self, index: int) -> None:
        cue = self.editor_cues[index]
        self.editor_cue_start.set(format_timecode(cue.start_ms))
        self.editor_cue_end.set(format_timecode(cue.end_ms))
        self.editor_cue_text.delete("1.0", "end")
        self.editor_cue_text.insert("1.0", cue.text)

    def apply_editor_cue(self) -> None:
        index = self._selected_editor_cue_index()
        if index is None:
            messagebox.showinfo("Chưa chọn phụ đề", "Chọn một dòng phụ đề trước khi sửa.")
            return
        try:
            start_ms = parse_timecode(self.editor_cue_start.get())
            end_ms = parse_timecode(self.editor_cue_end.get())
            duration_ms = round(self.editor_media_info.duration_seconds * 1000) if self.editor_media_info else None
            text = self.editor_cue_text.get("1.0", "end").strip()
            self.editor_cues = update_cue(
                self.editor_cues, index, start_ms=start_ms, end_ms=end_ms, text=text, duration_ms=duration_ms
            )
            selected = next(
                (i for i, cue in enumerate(self.editor_cues) if cue.start_ms == start_ms and cue.text == text),
                None,
            )
        except (ValueError, IndexError) as error:
            messagebox.showerror("Phụ đề không hợp lệ", str(error))
            return
        self._refresh_editor_cues(selected)
        self._sync_editor_timeline()
        self._refresh_editor_preview()

    def add_editor_cue(self) -> None:
        duration_ms = round(self.editor_media_info.duration_seconds * 1000) if self.editor_media_info else 60_000
        start_ms = min(max(0, round(float(self.editor_position.get()) * 1000)), max(0, duration_ms - 100))
        end_ms = min(duration_ms, start_ms + 2_000)
        cue = SubtitleCue(len(self.editor_cues) + 1, start_ms, max(start_ms + 100, end_ms), "Phụ đề mới")
        self.editor_cues = normalize_cues([*self.editor_cues, cue], duration_ms)
        selected = next((i for i, item in enumerate(self.editor_cues) if item.start_ms == cue.start_ms and item.text == cue.text), None)
        self._refresh_editor_cues(selected)
        self._sync_editor_timeline()

    def delete_editor_cue(self) -> None:
        index = self._selected_editor_cue_index()
        if index is None:
            return
        self.editor_cues = normalize_cues(self.editor_cues[:index] + self.editor_cues[index + 1 :])
        self._refresh_editor_cues(min(index, len(self.editor_cues) - 1) if self.editor_cues else None)
        self._sync_editor_timeline()
        self._refresh_editor_preview()

    def fit_editor_subtitles(self) -> None:
        if not self.editor_media_info or not self.editor_cues:
            return
        self.editor_cues = fit_cues_to_duration(
            self.editor_cues, round(self.editor_media_info.duration_seconds * 1000)
        )
        self._refresh_editor_cues(0)
        self._sync_editor_timeline()
        self._refresh_editor_preview()

    def _change_editor_cue_timing(self, index: int, start_ms: int, end_ms: int) -> None:
        if not 0 <= index < len(self.editor_cues):
            return
        cue = self.editor_cues[index]
        try:
            duration_ms = round(self.editor_media_info.duration_seconds * 1000) if self.editor_media_info else None
            self.editor_cues = update_cue(
                self.editor_cues,
                index,
                start_ms=start_ms,
                end_ms=end_ms,
                text=cue.text,
                duration_ms=duration_ms,
            )
        except ValueError:
            return
        selected = next((i for i, item in enumerate(self.editor_cues) if item.text == cue.text and item.start_ms == start_ms), None)
        self._refresh_editor_cues(selected)
        self._sync_editor_timeline()
        self._refresh_editor_preview()

    def _change_editor_audio_offset(self, milliseconds: int) -> None:
        self.editor_audio_offset.set(max(0, milliseconds))
        self._sync_editor_timeline()

    def _selected_editor_cue_index(self) -> int | None:
        selection = self.editor_cue_tree.selection()
        if not selection:
            return None
        match = re.fullmatch(r"cue-(\d+)", selection[0])
        return int(match.group(1)) if match else None

    def _on_editor_zoom(self, value: str) -> None:
        try:
            self.editor_timeline.set_zoom(float(value))
        except (ValueError, tk.TclError):
            pass

    def _on_editor_timeline_seek(self, milliseconds: int) -> None:
        was_playing = self._is_editor_playing()
        self._stop_editor_playback()
        self._set_editor_position(milliseconds / 1000, reveal=False)
        if was_playing:
            self._start_editor_playback()
        else:
            self._render_editor_still(milliseconds / 1000)

    def toggle_editor_playback(self) -> None:
        if self._is_editor_playing():
            self._stop_editor_playback()
        else:
            self._start_editor_playback()

    def _start_editor_playback(self) -> None:
        if not self.editor_media_info or not self.editor_video_path.get().strip():
            return
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            messagebox.showerror("Không phát được video", "Không tìm thấy FFmpeg. Hãy chạy install_ffmpeg.ps1.")
            return
        self._stop_editor_playback()
        start_seconds = max(0.0, float(self.editor_position.get()))
        if start_seconds >= self.editor_media_info.duration_seconds - 0.05:
            start_seconds = 0.0
            self._set_editor_position(0.0)
        subtitle_path = self._write_editor_preview_subtitles(round(start_seconds * 1000))
        command = build_editor_preview_command(
            ffmpeg,
            Path(self.editor_video_path.get()),
            start_seconds=start_seconds,
            width=EDITOR_PREVIEW_WIDTH,
            height=EDITOR_PREVIEW_HEIGHT,
            fps=EDITOR_PREVIEW_FPS,
            subtitle_path=subtitle_path,
            subtitle_font_size=self._editor_int(self.editor_subtitle_font_size, 22, 10, 72),
            subtitle_margin=self._editor_int(self.editor_subtitle_margin, 36, 0, 300),
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
            messagebox.showerror("Không phát được video", str(error))
            return
        self._editor_playback_process = process
        managed_media_processes.add(process)
        session = self._editor_playback_session
        stop_event = threading.Event()
        self._editor_playback_stop = stop_event
        self._start_editor_preview_audio(start_seconds, creationflags)
        self.editor_play_button.configure(text="Tạm dừng")
        self._editor_playback_worker = threading.Thread(
            target=self._read_editor_playback_frames,
            args=(process, stop_event, session, start_seconds),
            daemon=True,
        )
        self._editor_playback_worker.start()

    def _start_editor_preview_audio(self, start_seconds: float, creationflags: int) -> None:
        ffplay = find_ffplay()
        if not ffplay or not self.editor_media_info:
            return
        commands = build_editor_audio_preview_commands(
            ffplay,
            Path(self.editor_video_path.get()),
            start_seconds=start_seconds,
            source_volume=self._editor_int(self.editor_source_volume, 100, 0, 200),
            audio_path=Path(self.editor_audio_path.get()) if self.editor_audio_path.get() else None,
            audio_offset_ms=self._editor_int(self.editor_audio_offset, 0, 0, 86_400_000),
            external_volume=self._editor_int(self.editor_external_volume, 100, 0, 200),
            audio_mode=_code_from_label(self.editor_audio_mode.get(), AUDIO_MODE_LABELS, MIX_AUDIO),
            has_source_audio=self.editor_media_info.has_audio,
        )
        self._editor_audio_processes = []
        for command in commands:
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
            except OSError as error:
                self._append_log(f"Không phát được audio preview: {error}")
                continue
            managed_media_processes.add(process)
            self._editor_audio_processes.append(process)

    def _read_editor_playback_frames(
        self,
        process: subprocess.Popen[bytes],
        stop_event: threading.Event,
        session: int,
        start_seconds: float,
    ) -> None:
        frame_size = EDITOR_PREVIEW_WIDTH * EDITOR_PREVIEW_HEIGHT * 3
        frame_index = 0
        stdout = process.stdout
        if stdout is None:
            return
        while not stop_event.is_set():
            frame = self._editor_read_exact(stdout, frame_size)
            if len(frame) != frame_size:
                break
            position = min(
                self.editor_media_info.duration_seconds if self.editor_media_info else start_seconds,
                start_seconds + frame_index / EDITOR_PREVIEW_FPS,
            )
            frame_index += 1
            self._offer_editor_frame((session, frame, position))
        if stop_event.is_set():
            return
        return_code = process.wait()
        managed_media_processes.discard(process)
        final_position = start_seconds + frame_index / EDITOR_PREVIEW_FPS
        if return_code:
            stderr = process.stderr.read() if process.stderr else b""
            detail = stderr.decode("utf-8", errors="replace").strip() or f"FFmpeg exited with code {return_code}."
            self.events.put(("editor_playback_error", (session, detail)))
        else:
            self.events.put(("editor_playback_ended", (session, final_position)))

    def _render_editor_still(self, position_seconds: float) -> None:
        if not self.editor_media_info or not self.editor_video_path.get().strip():
            return
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return
        self._editor_still_session += 1
        session = self._editor_still_session
        video_path = Path(self.editor_video_path.get())
        subtitle_path = self._write_editor_preview_subtitles(round(position_seconds * 1000))
        command = build_editor_frame_command(
            ffmpeg,
            video_path,
            position_seconds=position_seconds,
            width=EDITOR_PREVIEW_WIDTH,
            height=EDITOR_PREVIEW_HEIGHT,
            subtitle_path=subtitle_path,
            subtitle_font_size=self._editor_int(self.editor_subtitle_font_size, 22, 10, 72),
            subtitle_margin=self._editor_int(self.editor_subtitle_margin, 36, 0, 300),
        )

        def worker() -> None:
            try:
                completed = subprocess.run(command, capture_output=True, check=False, timeout=30)
                frame_size = EDITOR_PREVIEW_WIDTH * EDITOR_PREVIEW_HEIGHT * 3
                if completed.returncode != 0 or len(completed.stdout) < frame_size:
                    detail = completed.stderr.decode("utf-8", errors="replace").strip() or "FFmpeg không tạo được preview."
                    raise RuntimeError(detail)
                self.events.put(("editor_still_ready", (session, completed.stdout[:frame_size], position_seconds)))
            except Exception as error:
                self.events.put(("editor_still_error", (session, error)))

        threading.Thread(target=worker, daemon=True).start()

    def _write_editor_preview_subtitles(self, offset_ms: int) -> Path | None:
        if not self.editor_cues:
            return None
        shifted: list[SubtitleCue] = []
        for cue in self.editor_cues:
            if cue.end_ms <= offset_ms:
                continue
            shifted.append(
                SubtitleCue(
                    index=len(shifted) + 1,
                    start_ms=max(0, cue.start_ms - offset_ms),
                    end_ms=cue.end_ms - offset_ms,
                    text=cue.text,
                )
            )
        if not shifted:
            return None
        path = Path(self._editor_preview_temp_dir.name) / f"editor_preview_{uuid.uuid4().hex}.srt"
        path.write_text(render_srt(shifted), encoding="utf-8")
        return path

    def _refresh_editor_preview(self) -> None:
        if self.editor_media_info and not self._is_editor_playing():
            self._render_editor_still(float(self.editor_position.get()))

    def _offer_editor_frame(self, frame: tuple[int, bytes, float]) -> None:
        try:
            self._editor_playback_frames.put_nowait(frame)
        except queue.Full:
            try:
                self._editor_playback_frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._editor_playback_frames.put_nowait(frame)
            except queue.Full:
                pass

    def _render_latest_editor_frame(self) -> None:
        latest: tuple[int, bytes, float] | None = None
        while True:
            try:
                latest = self._editor_playback_frames.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return
        session, frame, position = latest
        if session != self._editor_playback_session:
            return
        self._show_editor_frame(frame)
        if not self._editor_seek_dragging:
            self._set_editor_position(position, reveal=True)

    def _show_editor_frame(self, frame: bytes) -> None:
        header = f"P6\n{EDITOR_PREVIEW_WIDTH} {EDITOR_PREVIEW_HEIGHT}\n255\n".encode("ascii")
        self._editor_preview_image = tk.PhotoImage(data=header + frame, format="PPM")
        self.editor_preview_canvas.delete("editor-frame")
        self.editor_preview_canvas.delete("editor-placeholder")
        self.editor_preview_canvas.create_image(
            0, 0, image=self._editor_preview_image, anchor="nw", tags=("editor-frame",)
        )

    def _stop_editor_playback(self, *, update_ui: bool = True) -> None:
        self._editor_playback_session += 1
        self._editor_playback_stop.set()
        processes = [self._editor_playback_process, *self._editor_audio_processes]
        live = tuple(process for process in processes if process is not None)
        for process in live:
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
        self._editor_playback_process = None
        self._editor_audio_processes = []
        self._editor_playback_worker = None
        if live:
            threading.Thread(target=self._reap_editor_processes, args=(live,), daemon=True).start()
        while True:
            try:
                self._editor_playback_frames.get_nowait()
            except queue.Empty:
                break
        if update_ui:
            try:
                self.editor_play_button.configure(text="Phát")
            except tk.TclError:
                pass

    @staticmethod
    def _reap_editor_processes(processes: tuple[subprocess.Popen[bytes], ...]) -> None:
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
            finally:
                managed_media_processes.discard(process)

    @staticmethod
    def _editor_read_exact(stream: object, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = stream.read(remaining)  # type: ignore[attr-defined]
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _is_editor_playing(self) -> bool:
        return self._editor_playback_process is not None and self._editor_playback_process.poll() is None

    def _on_editor_seek_changed(self, value: str) -> None:
        try:
            self._update_editor_time_text(float(value))
        except ValueError:
            pass

    def _start_editor_seek(self, _event: tk.Event) -> None:
        self._editor_seek_dragging = True
        self._editor_resume_after_seek = self._is_editor_playing()
        if self._editor_resume_after_seek:
            self._stop_editor_playback()

    def _finish_editor_seek(self, _event: tk.Event) -> None:
        self._editor_seek_dragging = False
        position = float(self.editor_position.get())
        self._set_editor_position(position, reveal=True)
        if self._editor_resume_after_seek:
            self._editor_resume_after_seek = False
            self._start_editor_playback()
        else:
            self._render_editor_still(position)

    def _set_editor_position(self, seconds: float, *, reveal: bool = False) -> None:
        duration = self.editor_media_info.duration_seconds if self.editor_media_info else 0.0
        position = max(0.0, min(duration, seconds))
        self.editor_position.set(position)
        self._update_editor_time_text(position)
        self.editor_timeline.set_playhead(round(position * 1000), reveal=reveal)

    def _update_editor_time_text(self, position: float) -> None:
        duration = self.editor_media_info.duration_seconds if self.editor_media_info else 0.0
        self.editor_time_text.set(f"{self._format_editor_time(position)} / {self._format_editor_time(duration)}")

    @staticmethod
    def _format_editor_time(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{secs:02}" if hours else f"{minutes:02}:{secs:02}"

    def start_editor_export(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.editor_media_info or not self.editor_video_path.get().strip():
            messagebox.showwarning("Thiếu video", "Thêm video trước khi xuất.")
            return
        output_dir = Path(self.editor_output_dir.get().strip()).expanduser()
        options = EditorExportOptions(
            video_path=Path(self.editor_video_path.get()),
            audio_path=Path(self.editor_audio_path.get()) if self.editor_audio_path.get() else None,
            output_dir=output_dir,
            project_name=self.editor_project_name.get().strip(),
            subtitle_cues=tuple(self.editor_cues),
            audio_offset_ms=self._editor_int(self.editor_audio_offset, 0, 0, 86_400_000),
            audio_mode=_code_from_label(self.editor_audio_mode.get(), AUDIO_MODE_LABELS, MIX_AUDIO),
            source_volume=self._editor_int(self.editor_source_volume, 100, 0, 200),
            external_volume=self._editor_int(self.editor_external_volume, 100, 0, 200),
            resolution=_code_from_label(self.editor_resolution.get(), RESOLUTION_LABELS, ORIGINAL_RESOLUTION),
            fps=_code_from_label(self.editor_fps.get(), FPS_LABELS, SOURCE_FPS),
            encoder=_code_from_label(self.editor_encoder.get(), ENCODER_LABELS, AUTO_ENCODER),
            subtitle_font_size=self._editor_int(self.editor_subtitle_font_size, 22, 10, 72),
            subtitle_margin=self._editor_int(self.editor_subtitle_margin, 36, 0, 300),
        )
        self._stop_editor_playback()
        self._editor_export_cancel.clear()
        self._active_task = "editor_export"
        self._set_busy(True)
        self.status.set("Đang xuất video...")
        self.editor_progress.configure(value=0)
        self.editor_open_button.configure(state="disabled")

        def worker() -> None:
            try:
                result = export_editor_video(
                    options,
                    progress=lambda message: self.events.put(("editor_export_progress", message)),
                    cancellation=self._editor_export_cancel,
                )
                self.events.put(("done", result))
            except Exception as error:
                event = "editor_export_cancelled" if self._editor_export_cancel.is_set() else "error"
                self.events.put((event, error))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def stop_editor_export(self) -> None:
        if self._active_task == "editor_export":
            self._editor_export_cancel.set()
            self.editor_stop_button.configure(state="disabled")
            self.status.set("Đang dừng xuất video...")

    def open_editor_output(self) -> None:
        result = self._editor_last_result
        if result is not None:
            os.startfile(result.project_dir)

    def _handle_editor_event(self, event: str, payload: object) -> bool:
        if event == "editor_bundle_loaded":
            video, info, audio, audio_duration, subtitle, cues = payload
            video_asset = EditorAsset(
                asset_id=self._editor_asset_id(VIDEO_ASSET, str(video)),
                kind=VIDEO_ASSET,
                path=str(video),
                duration_seconds=info.duration_seconds,
                width=info.width,
                height=info.height,
                fps=info.fps,
                has_audio=info.has_audio,
            )
            audio_asset = EditorAsset(
                asset_id=self._editor_asset_id(AUDIO_ASSET, str(audio)),
                kind=AUDIO_ASSET,
                path=str(audio),
                duration_seconds=float(audio_duration),
            )
            subtitle_asset = EditorAsset(
                asset_id=self._editor_asset_id(SUBTITLE_ASSET, str(subtitle)),
                kind=SUBTITLE_ASSET,
                path=str(subtitle),
                cues=tuple(cues),
            )
            for asset in (video_asset, audio_asset, subtitle_asset):
                self._store_editor_asset(asset)
            self._activate_editor_asset(video_asset.asset_id, 0)
            self._activate_editor_asset(audio_asset.asset_id, 0)
            self._activate_editor_asset(subtitle_asset.asset_id, 0)
            self.main_notebook.select(self.editor_tab)
            self.status.set("Đã đưa video, voice và SRT vào timeline")
            self._append_log("Đã nạp bản lồng tiếng vào Dựng video.")
            return True
        if event == "editor_bundle_error":
            self.status.set("Không đưa được bản lồng tiếng sang editor")
            messagebox.showerror("Không nạp được bản lồng tiếng", str(payload))
            return True
        if event == "editor_video_loaded":
            asset_id, path, info = payload if isinstance(payload, tuple) else ("", "", None)
            if isinstance(info, EditorMediaInfo):
                asset = EditorAsset(
                    asset_id=str(asset_id),
                    kind=VIDEO_ASSET,
                    path=str(path),
                    duration_seconds=info.duration_seconds,
                    width=info.width,
                    height=info.height,
                    fps=info.fps,
                    has_audio=info.has_audio,
                )
                self._store_editor_asset(asset)
                self.status.set("Đã nhập video")
                self._append_log(f"Media Bin video: {asset.name}.")
            return True
        if event == "editor_media_error":
            _asset_id, error = payload if isinstance(payload, tuple) else ("", payload)
            self.status.set("Không đọc được video")
            messagebox.showerror("Không đọc được video", str(error))
            return True
        if event == "editor_audio_loaded":
            asset_id, path, duration = payload if isinstance(payload, tuple) else ("", "", 0.0)
            asset = EditorAsset(
                asset_id=str(asset_id),
                kind=AUDIO_ASSET,
                path=str(path),
                duration_seconds=float(duration),
            )
            self._store_editor_asset(asset)
            self.status.set("Đã nhập audio")
            self._append_log(f"Media Bin audio: {asset.name}.")
            return True
        if event == "editor_audio_error":
            _asset_id, error = payload if isinstance(payload, tuple) else ("", payload)
            self.status.set("Không đọc được audio")
            messagebox.showerror("Không đọc được audio", str(error))
            return True
        if event == "editor_still_ready":
            session, frame, position = payload if isinstance(payload, tuple) else (-1, b"", 0.0)
            if int(session) == self._editor_still_session and isinstance(frame, bytes):
                self._show_editor_frame(frame)
                self._set_editor_position(float(position))
            return True
        if event == "editor_still_error":
            session, error = payload if isinstance(payload, tuple) else (-1, payload)
            if int(session) == self._editor_still_session:
                self._append_log(f"Preview editor lỗi: {error}")
            return True
        if event == "editor_playback_ended":
            session, position = payload if isinstance(payload, tuple) else (-1, 0.0)
            if int(session) == self._editor_playback_session:
                self._stop_editor_playback()
                self._set_editor_position(float(position), reveal=True)
            return True
        if event == "editor_playback_error":
            session, error = payload if isinstance(payload, tuple) else (-1, payload)
            if int(session) == self._editor_playback_session:
                self._stop_editor_playback()
                self._append_log(f"Playback editor lỗi: {error}")
            return True
        if event == "editor_export_progress":
            message = str(payload)
            match = re.search(r"(\d+)%", message)
            if match:
                self.editor_progress.configure(value=int(match.group(1)))
            self.status.set(message)
            return True
        if event == "editor_export_cancelled":
            self.editor_progress.configure(value=0)
            self._active_task = None
            self._set_busy(False)
            self.status.set("Đã dừng xuất video")
            self._append_log(str(payload))
            return True
        return False

    def _finish_editor_result(self, result: EditorExportResult) -> None:
        self._editor_last_result = result
        self.editor_progress.configure(value=100)
        self.editor_open_button.configure(state="normal")
        self._append_log(f"Video: {result.video_path}")
        if result.subtitle_path:
            self._append_log(f"SRT: {result.subtitle_path}")
        self._append_log(f"Manifest: {result.manifest_path}")
        for warning in result.warnings:
            self._append_log(f"Warning: {warning}")

    @staticmethod
    def _editor_int(variable: tk.Variable, default: int, minimum: int, maximum: int) -> int:
        try:
            value = round(float(variable.get()))
        except (tk.TclError, TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))


def _code_from_label(label: str, labels: dict[str, str], default: str) -> str:
    return next((code for code, value in labels.items() if value == label), default)
