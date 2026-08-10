from __future__ import annotations

import tkinter as tk
from dataclasses import asdict, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

from ....voice.srt import SubtitleCue, parse_srt
from ....voice.transcription import VideoSubtitleDraft
from .model import (
    DubbingSegment,
    build_dubbing_segments,
    merge_dubbing_segments,
    split_dubbing_segment,
    validate_dubbing_segments,
)


class DubbingWorkspaceGuiMixin:
    def _init_dubbing_workspace_state(self) -> None:
        self.omnivoice_dubbing_segments: list[DubbingSegment] = []
        self.omnivoice_dubbing_cast: dict[str, str] = {}
        self.omnivoice_dubbing_project_id = ""
        self.omnivoice_dubbing_project_choice = tk.StringVar(value="")
        self.omnivoice_dubbing_search = tk.StringVar(value="")
        self.omnivoice_dubbing_speaker_filter = tk.StringVar(value="Tất cả")
        self.omnivoice_dubbing_speaker = tk.StringVar(value="Default")
        self.omnivoice_dubbing_profile = tk.StringVar(value="")
        self.omnivoice_dubbing_start = tk.StringVar(value="0.000")
        self.omnivoice_dubbing_end = tk.StringVar(value="1.000")
        self.omnivoice_dubbing_speed = tk.DoubleVar(value=1.0)
        self.omnivoice_dubbing_volume = tk.DoubleVar(value=1.0)
        self.omnivoice_dubbing_status = tk.StringVar(value="Chưa có segment")

    def _build_omnivoice_dubbing_segment_tab(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=8)
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2, minsize=310)
        page.rowconfigure(1, weight=1)
        notebook.add(page, text="Segments")
        self.omnivoice_dubbing_segment_tab = page

        toolbar = ttk.Frame(page)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        toolbar.columnconfigure(0, weight=1)
        search = ttk.Entry(toolbar, textvariable=self.omnivoice_dubbing_search)
        search.grid(row=0, column=0, sticky="ew")
        search.bind("<KeyRelease>", lambda _event: self._refresh_dubbing_segment_tree())
        speaker_filter = ttk.Combobox(
            toolbar,
            textvariable=self.omnivoice_dubbing_speaker_filter,
            values=("Tất cả",),
            state="readonly",
            width=16,
        )
        speaker_filter.grid(row=0, column=1, padx=(7, 0))
        speaker_filter.bind(
            "<<ComboboxSelected>>", lambda _event: self._refresh_dubbing_segment_tree()
        )
        self.omnivoice_dubbing_speaker_filter_combo = speaker_filter
        for column, (label, command) in enumerate(
            (
                ("Nhập SRT", self._import_dubbing_srt),
                ("QC", self._show_dubbing_qc),
                ("Lưu project", self._save_dubbing_project),
                ("Mở project", self._open_dubbing_project),
            ),
            start=2,
        ):
            button = ttk.Button(toolbar, text=label, command=command)
            button.grid(row=0, column=column, padx=(7, 0))
            self.omnivoice_mutable_widgets.append(button)
        self.omnivoice_mutable_widgets.extend((search, speaker_filter))

        table = ttk.Frame(page, style="Panel.TFrame", padding=6)
        table.grid(row=1, column=0, sticky="nsew", padx=(0, 9))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            table,
            columns=("start", "end", "speaker", "text", "qc"),
            show="headings",
            selectmode="browse",
        )
        columns = (
            ("start", "Bắt đầu", 78, False),
            ("end", "Kết thúc", 78, False),
            ("speaker", "Speaker", 90, False),
            ("text", "Lời dịch", 320, True),
            ("qc", "QC", 55, False),
        )
        for name, label, width, stretch in columns:
            tree.heading(name, text=label)
            tree.column(name, width=width, stretch=stretch)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)
        tree.bind("<<TreeviewSelect>>", self._load_selected_dubbing_segment)
        self.omnivoice_dubbing_tree = tree

        inspector = ttk.Frame(page, style="Panel.TFrame", padding=10)
        inspector.grid(row=1, column=1, sticky="nsew")
        inspector.columnconfigure(1, weight=1)
        inspector.rowconfigure(5, weight=1)
        fields = (
            ("Bắt đầu (giây)", self.omnivoice_dubbing_start),
            ("Kết thúc (giây)", self.omnivoice_dubbing_end),
        )
        for row, (label, variable) in enumerate(fields):
            ttk.Label(inspector, text=label, style="Panel.TLabel").grid(
                row=row, column=0, sticky="w", pady=3
            )
            entry = ttk.Entry(inspector, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=3)
            self.omnivoice_mutable_widgets.append(entry)
        ttk.Label(inspector, text="Speaker", style="Panel.TLabel").grid(
            row=2, column=0, sticky="w", pady=3
        )
        speaker = ttk.Combobox(
            inspector,
            textvariable=self.omnivoice_dubbing_speaker,
            values=("Default",),
            state="normal",
        )
        speaker.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=3)
        self.omnivoice_editable_combos.append(speaker)
        self.omnivoice_dubbing_speaker_combo = speaker
        ttk.Label(inspector, text="Profile", style="Panel.TLabel").grid(
            row=3, column=0, sticky="w", pady=3
        )
        profile = ttk.Combobox(
            inspector,
            textvariable=self.omnivoice_dubbing_profile,
            state="readonly",
        )
        profile.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=3)
        self.omnivoice_profile_combos.append(profile)
        ttk.Label(inspector, text="Lời dịch", style="Panel.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(7, 3)
        )
        text = tk.Text(inspector, height=7, wrap="word", undo=True, font=("Segoe UI", 9))
        text.grid(row=5, column=0, columnspan=2, sticky="nsew")
        self.omnivoice_dubbing_text = text

        tuning = ttk.Frame(inspector, style="Surface.TFrame")
        tuning.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tuning.columnconfigure((1, 3), weight=1)
        ttk.Label(tuning, text="Tốc độ", style="Panel.TLabel").grid(row=0, column=0)
        speed = ttk.Spinbox(
            tuning,
            from_=0.5,
            to=1.5,
            increment=0.05,
            textvariable=self.omnivoice_dubbing_speed,
            width=7,
        )
        speed.grid(row=0, column=1, sticky="ew", padx=(5, 10))
        ttk.Label(tuning, text="Âm lượng", style="Panel.TLabel").grid(row=0, column=2)
        volume = ttk.Spinbox(
            tuning,
            from_=0.0,
            to=2.0,
            increment=0.05,
            textvariable=self.omnivoice_dubbing_volume,
            width=7,
        )
        volume.grid(row=0, column=3, sticky="ew", padx=(5, 0))

        actions = ttk.Frame(inspector, style="Surface.TFrame")
        actions.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(9, 0))
        actions.columnconfigure((0, 1, 2), weight=1)
        action_specs = (
            ("Áp dụng", self._apply_selected_dubbing_segment),
            ("Nghe thử", self._preview_selected_dubbing_segment),
            ("Tách", self._split_selected_dubbing_segment),
            ("Ghép câu sau", self._merge_selected_dubbing_segment),
            ("Thêm", self._add_dubbing_segment),
            ("Xóa", self._delete_selected_dubbing_segment),
        )
        for index, (label, command) in enumerate(action_specs):
            button = ttk.Button(actions, text=label, command=command)
            button.grid(row=index // 3, column=index % 3, sticky="ew", padx=2, pady=2)
            self.omnivoice_mutable_widgets.append(button)
        ttk.Label(inspector, textvariable=self.omnivoice_dubbing_status, style="Panel.TLabel").grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(7, 0)
        )
        self.omnivoice_mutable_widgets.extend((speaker, profile, text, speed, volume))
        self._refresh_dubbing_projects()

    def load_dubbing_segments_from_draft(self, draft: VideoSubtitleDraft) -> None:
        self.omnivoice_dubbing_segments = list(
            build_dubbing_segments(draft.source_cues, draft.translated_cues)
        )
        self.omnivoice_dubbing_cast = {}
        self.omnivoice_dubbing_project_id = ""
        self._refresh_dubbing_segment_tree()

    def _import_dubbing_srt(self) -> None:
        selected = filedialog.askopenfilename(
            title="Nhập phụ đề vào Dubbing",
            filetypes=[("SubRip", "*.srt"), ("Tất cả file", "*.*")],
        )
        if not selected:
            return
        try:
            cues = tuple(parse_srt(Path(selected).read_text(encoding="utf-8-sig")))
        except (OSError, UnicodeError, ValueError) as error:
            messagebox.showerror("Không đọc được SRT", str(error))
            return
        current = self.subtitle_draft
        use_as_translation = current is not None and messagebox.askyesno(
            "Nhập SRT",
            "Dùng file này làm sub dịch? Chọn No để thay cả sub gốc.",
        )
        if current is not None and use_as_translation:
            draft = replace(current, translated_cues=cues)
        else:
            source_video_value = self.video_path.get().strip()
            source_video = Path(source_video_value or selected).expanduser()
            draft = VideoSubtitleDraft(
                source_video=source_video,
                project_name=self.project_name.get().strip() or Path(selected).stem,
                audio_path=source_video,
                source_language=self.video_source_language.get(),
                target_language=self.video_target_language.get(),
                whisper_model="imported-srt",
                ai_provider="",
                ai_model="",
                ai_base_url="",
                source_cues=cues,
                translated_cues=None,
                warnings=[],
            )
        self._replace_subtitle_draft(draft)
        self._load_subtitle_draft(draft)
        self.load_dubbing_segments_from_draft(draft)
        self.subtitle_notebook.select(self.omnivoice_dubbing_segment_tab)
        self._set_busy(False)

    def _filtered_dubbing_segments(self) -> tuple[DubbingSegment, ...]:
        query = self.omnivoice_dubbing_search.get().strip().casefold()
        speaker = self.omnivoice_dubbing_speaker_filter.get()
        return tuple(
            item
            for item in self.omnivoice_dubbing_segments
            if (speaker == "Tất cả" or item.speaker_id == speaker)
            and (
                not query
                or query in f"{item.source_text} {item.text} {item.speaker_id}".casefold()
            )
        )

    def _refresh_dubbing_segment_tree(self, selected_id: str = "") -> None:
        if not hasattr(self, "omnivoice_dubbing_tree"):
            return
        speakers = tuple(dict.fromkeys(item.speaker_id for item in self.omnivoice_dubbing_segments))
        self.omnivoice_dubbing_speaker_filter_combo.configure(values=("Tất cả", *speakers))
        self.omnivoice_dubbing_speaker_combo.configure(values=("Default", *speakers))
        issues = validate_dubbing_segments(tuple(self.omnivoice_dubbing_segments))
        issue_codes: dict[str, list[str]] = {}
        for issue in issues:
            issue_codes.setdefault(issue.segment_id, []).append(issue.code)
        tree = self.omnivoice_dubbing_tree
        tree.delete(*tree.get_children())
        for segment in self._filtered_dubbing_segments():
            tree.insert(
                "",
                "end",
                iid=segment.segment_id,
                values=(
                    _format_seconds(segment.start_ms),
                    _format_seconds(segment.end_ms),
                    segment.speaker_id,
                    segment.text.replace("\n", " "),
                    ", ".join(issue_codes.get(segment.segment_id, ())) or "OK",
                ),
            )
        if selected_id and tree.exists(selected_id):
            tree.selection_set(selected_id)
            tree.focus(selected_id)
            tree.see(selected_id)
        self.omnivoice_dubbing_status.set(
            f"{len(self.omnivoice_dubbing_segments)} segment | {len(speakers)} speaker | {len(issues)} cảnh báo"
        )

    def _selected_dubbing_segment(self) -> DubbingSegment | None:
        selection = self.omnivoice_dubbing_tree.selection()
        if not selection:
            return None
        segment_id = selection[0]
        return next(
            (item for item in self.omnivoice_dubbing_segments if item.segment_id == segment_id),
            None,
        )

    def _load_selected_dubbing_segment(self, _event: tk.Event | None = None) -> None:
        segment = self._selected_dubbing_segment()
        if segment is None:
            return
        self.omnivoice_dubbing_start.set(_format_seconds(segment.start_ms))
        self.omnivoice_dubbing_end.set(_format_seconds(segment.end_ms))
        self.omnivoice_dubbing_speaker.set(segment.speaker_id)
        profile_id = segment.profile_id or self.omnivoice_dubbing_cast.get(segment.speaker_id, "")
        label = next(
            (
                label
                for label, profile in self._omnivoice_profile_by_label.items()
                if profile.profile_id == profile_id
            ),
            "",
        )
        self.omnivoice_dubbing_profile.set(label)
        self.omnivoice_dubbing_text.delete("1.0", "end")
        self.omnivoice_dubbing_text.insert("1.0", segment.text)
        self.omnivoice_dubbing_speed.set(segment.speed)
        self.omnivoice_dubbing_volume.set(segment.volume)

    def _apply_selected_dubbing_segment(self) -> None:
        segment = self._selected_dubbing_segment()
        if segment is None:
            return
        try:
            start_ms = _parse_seconds(self.omnivoice_dubbing_start.get())
            end_ms = _parse_seconds(self.omnivoice_dubbing_end.get())
            if end_ms <= start_ms:
                raise ValueError("Thời gian kết thúc phải sau thời gian bắt đầu.")
            text = self.omnivoice_dubbing_text.get("1.0", "end").strip()
            speaker = self.omnivoice_dubbing_speaker.get().strip() or "Default"
            profile = self._omnivoice_profile_by_label.get(self.omnivoice_dubbing_profile.get())
            updated = replace(
                segment,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                speaker_id=speaker,
                profile_id=profile.profile_id if profile else "",
                speed=max(0.5, min(1.5, float(self.omnivoice_dubbing_speed.get()))),
                volume=max(0.0, min(2.0, float(self.omnivoice_dubbing_volume.get()))),
                preview_path="",
            )
        except (tk.TclError, TypeError, ValueError) as error:
            messagebox.showerror("Segment chưa hợp lệ", str(error))
            return
        if profile:
            self.omnivoice_dubbing_cast[speaker] = profile.profile_id
        self._replace_dubbing_segment(updated)

    def _replace_dubbing_segment(self, replacement: DubbingSegment) -> None:
        self.omnivoice_dubbing_segments = [
            replacement if item.segment_id == replacement.segment_id else item
            for item in self.omnivoice_dubbing_segments
        ]
        self.omnivoice_dubbing_segments.sort(key=lambda item: (item.start_ms, item.end_ms))
        self._refresh_dubbing_segment_tree(replacement.segment_id)

    def _split_selected_dubbing_segment(self) -> None:
        self._apply_selected_dubbing_segment()
        segment = self._selected_dubbing_segment()
        if segment is None:
            return
        try:
            left, right = split_dubbing_segment(segment)
        except ValueError as error:
            messagebox.showerror("Không tách được segment", str(error))
            return
        index = self.omnivoice_dubbing_segments.index(segment)
        self.omnivoice_dubbing_segments[index : index + 1] = [left, right]
        self._refresh_dubbing_segment_tree(right.segment_id)

    def _merge_selected_dubbing_segment(self) -> None:
        self._apply_selected_dubbing_segment()
        segment = self._selected_dubbing_segment()
        if segment is None:
            return
        index = self.omnivoice_dubbing_segments.index(segment)
        if index >= len(self.omnivoice_dubbing_segments) - 1:
            return
        following = self.omnivoice_dubbing_segments[index + 1]
        merged = merge_dubbing_segments(segment, following)
        self.omnivoice_dubbing_segments[index : index + 2] = [merged]
        self._refresh_dubbing_segment_tree(merged.segment_id)

    def _add_dubbing_segment(self) -> None:
        selected = self._selected_dubbing_segment()
        start_ms = selected.end_ms if selected else (
            self.omnivoice_dubbing_segments[-1].end_ms if self.omnivoice_dubbing_segments else 0
        )
        segment = DubbingSegment(
            segment_id=f"seg-{uuid4().hex[:10]}",
            start_ms=start_ms,
            end_ms=start_ms + 1_000,
            source_text="",
            text="",
        )
        self.omnivoice_dubbing_segments.append(segment)
        self._refresh_dubbing_segment_tree(segment.segment_id)

    def _delete_selected_dubbing_segment(self) -> None:
        segment = self._selected_dubbing_segment()
        if segment is None:
            return
        self.omnivoice_dubbing_segments = [
            item for item in self.omnivoice_dubbing_segments if item.segment_id != segment.segment_id
        ]
        self._refresh_dubbing_segment_tree()

    def _show_dubbing_qc(self) -> None:
        issues = validate_dubbing_segments(tuple(self.omnivoice_dubbing_segments))
        if not issues:
            messagebox.showinfo("Dubbing QC", "Không phát hiện lỗi timing hoặc độ dài lời thoại.")
            return
        lines = [f"- {issue.segment_id}: {issue.message}" for issue in issues[:20]]
        if len(issues) > 20:
            lines.append(f"... và {len(issues) - 20} cảnh báo khác")
        messagebox.showwarning("Dubbing QC", "\n".join(lines))

    def _preview_selected_dubbing_segment(self) -> None:
        self._apply_selected_dubbing_segment()
        segment = self._selected_dubbing_segment()
        if segment is not None:
            self._start_dubbing_segment_preview(segment)

    def _save_dubbing_project(self) -> None:
        if not self.omnivoice_dubbing_segments:
            return
        project = self.omnivoice_workspace_repository.save_project(
            workspace="dubbing",
            name=self.project_name.get().strip() or "Video Dubbing",
            project_id=self.omnivoice_dubbing_project_id,
            payload={
                "source_video": self.video_path.get().strip(),
                "source_language": self.video_source_language.get(),
                "target_language": self.video_target_language.get(),
                "segments": [asdict(item) for item in self.omnivoice_dubbing_segments],
                "cast": self.omnivoice_dubbing_cast,
            },
        )
        self.omnivoice_dubbing_project_id = project.project_id
        self._refresh_dubbing_projects(project.project_id)
        self.omnivoice_dubbing_status.set(f"Đã lưu project: {project.name}")

    def _refresh_dubbing_projects(self, selected_id: str = "") -> None:
        projects = self.omnivoice_workspace_repository.list_projects("dubbing")
        self._omnivoice_dubbing_project_by_label = {
            f"{item.name} | {item.updated_at[:16].replace('T', ' ')}": item
            for item in projects
        }
        if hasattr(self, "omnivoice_dubbing_project_combo"):
            self.omnivoice_dubbing_project_combo.configure(
                values=tuple(self._omnivoice_dubbing_project_by_label)
            )
        if selected_id:
            label = next(
                (
                    label
                    for label, item in self._omnivoice_dubbing_project_by_label.items()
                    if item.project_id == selected_id
                ),
                "",
            )
            self.omnivoice_dubbing_project_choice.set(label)

    def _open_dubbing_project(self) -> None:
        projects = self.omnivoice_workspace_repository.list_projects("dubbing")
        if not projects:
            messagebox.showinfo("Dubbing projects", "Chưa có project đã lưu.")
            return
        chooser = tk.Toplevel(self.root)
        chooser.title("Mở Dubbing project")
        chooser.geometry("560x300")
        chooser.transient(self.root)
        chooser.grab_set()
        frame = ttk.Frame(chooser, padding=10)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=("name", "updated"), show="headings")
        tree.heading("name", text="Project")
        tree.heading("updated", text="Cập nhật")
        tree.column("name", width=330)
        tree.column("updated", width=170)
        tree.pack(fill="both", expand=True)
        for project in projects:
            tree.insert(
                "",
                "end",
                iid=project.project_id,
                values=(project.name, project.updated_at[:19].replace("T", " ")),
            )

        def open_selected() -> None:
            selection = tree.selection()
            if not selection:
                return
            project = self.omnivoice_workspace_repository.get_project(selection[0])
            if project is not None:
                self._restore_dubbing_project(project)
            chooser.destroy()

        ttk.Button(frame, text="Mở", style="Accent.TButton", command=open_selected).pack(
            fill="x", pady=(8, 0)
        )

    def _restore_dubbing_project(self, project) -> None:
        raw_segments = project.payload.get("segments")
        if not isinstance(raw_segments, list):
            return
        segments = [
            DubbingSegment(**item)
            for item in raw_segments
            if isinstance(item, dict)
        ]
        if not segments:
            return
        self.omnivoice_dubbing_segments = segments
        raw_cast = project.payload.get("cast")
        self.omnivoice_dubbing_cast = (
            {str(key): str(value) for key, value in raw_cast.items()}
            if isinstance(raw_cast, dict)
            else {}
        )
        self.omnivoice_dubbing_project_id = project.project_id
        self.project_name.set(project.name)
        source_video = str(project.payload.get("source_video") or "")
        self.video_path.set(source_video)
        source_cues = tuple(
            SubtitleCue(
                index=index,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                text=f"[speaker:{item.speaker_id}] {item.source_text}",
            )
            for index, item in enumerate(segments, start=1)
        )
        translated_cues = tuple(
            SubtitleCue(index, item.start_ms, item.end_ms, item.text)
            for index, item in enumerate(segments, start=1)
        )
        draft = VideoSubtitleDraft(
            source_video=Path(source_video),
            project_name=project.name,
            audio_path=Path(source_video),
            source_language=str(project.payload.get("source_language") or "auto"),
            target_language=str(project.payload.get("target_language") or "vi"),
            whisper_model="project",
            ai_provider="project",
            ai_model="project",
            ai_base_url="",
            source_cues=source_cues,
            translated_cues=translated_cues,
            warnings=[],
        )
        self._replace_subtitle_draft(draft)
        self._load_subtitle_draft(draft)
        self._refresh_dubbing_segment_tree()
        self.subtitle_notebook.select(self.omnivoice_dubbing_segment_tab)
        self._set_busy(False)


def _format_seconds(value_ms: int) -> str:
    return f"{max(0, int(value_ms)) / 1000:.3f}"


def _parse_seconds(value: str) -> int:
    normalized = value.strip().replace(",", ".")
    if ":" in normalized:
        parts = normalized.split(":")
        if len(parts) == 2:
            seconds = int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        else:
            raise ValueError("Timecode không hợp lệ.")
    else:
        seconds = float(normalized)
    if seconds < 0:
        raise ValueError("Timecode không được âm.")
    return round(seconds * 1000)
