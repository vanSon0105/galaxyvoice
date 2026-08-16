from __future__ import annotations

import os
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from ...common.cache import read_json
from ...voice.srt import parse_srt
from ...voice.transcription import VideoSubtitleDraft
from ..models import AUTO_MODE, CLONE_MODE, DESIGN_MODE, OmniVoiceGenerationOptions
from ..runtime import inspect_runtime
from .audiobook import AudiobookWorkspaceGuiMixin
from .common import WorkspaceRepository
from .common.editor_gui import EditableLongformGuiMixin
from .dubbing.gui import DubbingWorkspaceGuiMixin
from .dubbing.model import plan_dubbing_segments
from .editable import EditableLongformDocument, EditableLongformItem
from .gallery import VoiceArchetype, list_voice_archetypes, voice_archetype_categories
from .imports import load_audiobook_source
from .longform import (
    LongformPlan,
    detect_longform_workspace_kind,
    parse_audiobook_script,
    parse_story_script,
    plan_dubbing_cues,
)
from .renderer import LongformWorkspaceResult, render_longform_plan
from .transcripts import TranscriptEntry, TranscriptStore
from .stories import build_stories_workspace_editor


_STORY_SAMPLE = """# Mở đầu
Người kể: Một buổi sáng yên tĩnh bắt đầu. [pause 500ms]
Lan: [slow]Hôm nay chúng ta sẽ đi đâu?[/slow]
Minh: Đi tìm một câu chuyện mới.
"""

_AUDIOBOOK_SAMPLE = """# Chương 1 - Khởi đầu
[voice:Người kể] Mỗi hành trình đều bắt đầu bằng một lựa chọn.
[pause 700ms]

# Chương 2 - Cuộc gặp
[voice:Lan] Tôi đã đợi ở đây rất lâu rồi.
"""


class OmniVoiceWorkspaceGuiMixin(
    DubbingWorkspaceGuiMixin,
    EditableLongformGuiMixin,
    AudiobookWorkspaceGuiMixin,
):
    def _init_omnivoice_workspace_state(self) -> None:
        self.omnivoice_workspace_result: LongformWorkspaceResult | None = None
        self.omnivoice_last_dub_result: LongformWorkspaceResult | None = None
        self.omnivoice_story_project_name = tk.StringVar(value="omnivoice-story")
        self.omnivoice_audiobook_project_name = tk.StringVar(value="omnivoice-audiobook")
        self.omnivoice_audiobook_title = tk.StringVar(value="")
        self.omnivoice_audiobook_author = tk.StringVar(value="")
        self.omnivoice_audiobook_export_m4b = tk.BooleanVar(value=True)
        self.omnivoice_story_export_stems = tk.BooleanVar(value=False)
        self.omnivoice_audiobook_export_stems = tk.BooleanVar(value=False)
        self.omnivoice_story_cast_choice = tk.StringVar(value="")
        self.omnivoice_audiobook_cast_choice = tk.StringVar(value="")
        self.omnivoice_longform_workspace_mode = tk.StringVar(value="stories")
        self._omnivoice_active_longform_kind = "stories"
        self.omnivoice_story_cast: dict[str, str] = {}
        self.omnivoice_audiobook_cast: dict[str, str] = {}
        self.omnivoice_gallery_search = tk.StringVar(value="")
        self.omnivoice_gallery_favorites_only = tk.BooleanVar(value=False)
        self.omnivoice_gallery_page = 0
        self.omnivoice_gallery_page_status = tk.StringVar(value="Trang 1/1")
        self.omnivoice_history_search = tk.StringVar(value="")
        self.omnivoice_history_workspace = tk.StringVar(value="Tất cả")
        self.omnivoice_history_starred_only = tk.BooleanVar(value=False)
        self.omnivoice_gallery_category = tk.StringVar(value="Tất cả")
        self.omnivoice_transcript_search = tk.StringVar(value="")
        self.omnivoice_transcript_store = TranscriptStore(
            self.config_path.with_name("transcriptions.json")
        )
        self.omnivoice_workspace_repository = WorkspaceRepository(
            self.config_path.with_name("omnivoice_workspaces.json")
        )
        gallery_projects = self.omnivoice_workspace_repository.list_projects("gallery")
        favorites_project = next(
            (item for item in gallery_projects if item.name == "favorites"),
            None,
        )
        raw_favorites = favorites_project.payload.get("ids") if favorites_project else []
        self.omnivoice_gallery_favorites = (
            {str(value) for value in raw_favorites}
            if isinstance(raw_favorites, list)
            else set()
        )
        self.omnivoice_gallery_favorites_project_id = (
            favorites_project.project_id if favorites_project else ""
        )
        self._init_dubbing_workspace_state()
        self._init_editable_longform_state()
        self._init_audiobook_workspace_state()

    def _build_omnivoice_workspace_tabs(self, notebook: ttk.Notebook) -> None:
        self._build_omnivoice_dubbing_segment_tab(self.subtitle_notebook)
        self._build_omnivoice_longform_studio(notebook)
        self._build_omnivoice_gallery_workspace(notebook)
        self._build_omnivoice_transcripts_workspace(notebook)

    def _build_omnivoice_longform_studio(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=(8, 6, 8, 8))
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        notebook.add(page, text="Truyện & Sách nói")
        self.omnivoice_longform_tab = page

        mode_bar = ttk.Frame(page, style="Surface.TFrame")
        mode_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for column, (label, kind) in enumerate(
            (("Truyện nhiều vai", "stories"), ("Sách nói", "audiobook"))
        ):
            button = ttk.Radiobutton(
                mode_bar,
                text=label,
                value=kind,
                variable=self.omnivoice_longform_workspace_mode,
                style="Segment.TRadiobutton",
                command=lambda selected=kind: self._select_omnivoice_longform_mode(selected),
            )
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4, 0))
            self.omnivoice_mutable_widgets.append(button)
        mode_bar.columnconfigure((0, 1), weight=1)
        auto_button = ttk.Button(
            mode_bar,
            text="Tự nhận diện",
            style="Tool.TButton",
            command=self._auto_select_omnivoice_longform_mode,
        )
        auto_button.grid(row=0, column=2, padx=(8, 0))
        self.omnivoice_longform_auto_button = auto_button
        self.omnivoice_mutable_widgets.append(auto_button)

        workspace_host = ttk.Frame(page, style="Surface.TFrame")
        workspace_host.grid(row=1, column=0, sticky="nsew")
        workspace_host.columnconfigure(0, weight=1)
        workspace_host.rowconfigure(0, weight=1)
        self.omnivoice_longform_workspace_frames: dict[str, ttk.Frame] = {}
        for kind in ("stories", "audiobook"):
            self.omnivoice_longform_workspace_frames[kind] = (
                self._build_omnivoice_longform_workspace(workspace_host, kind)
            )
        self._select_omnivoice_longform_mode("stories", sync_project=False)

    def _select_omnivoice_longform_mode(
        self,
        kind: str,
        *,
        sync_project: bool = True,
    ) -> None:
        if kind not in {"stories", "audiobook"}:
            raise ValueError(f"Unsupported long-form workspace: {kind}")
        previous = self._omnivoice_active_longform_kind
        if sync_project and previous != kind:
            self._sync_omnivoice_longform_project(previous, kind)
        self.omnivoice_longform_workspace_mode.set(kind)
        self._omnivoice_active_longform_kind = kind
        for frame in self.omnivoice_longform_workspace_frames.values():
            frame.grid_remove()
        self.omnivoice_longform_workspace_frames[kind].grid()

    def _auto_select_omnivoice_longform_mode(self) -> None:
        source_kind = self._omnivoice_active_longform_kind
        source_widget = getattr(
            self,
            f"omnivoice_{source_kind}_text",
        )
        source = source_widget.get("1.0", "end").strip()
        if not source:
            messagebox.showinfo("Tự nhận diện", "Hãy nhập nội dung trước.")
            return
        detected_kind = detect_longform_workspace_kind(source)
        if detected_kind != source_kind:
            self._sync_omnivoice_longform_project(
                source_kind,
                detected_kind,
                source_format=detected_kind,
            )
        self._select_omnivoice_longform_mode(detected_kind, sync_project=False)

    def _sync_omnivoice_longform_project(
        self,
        source_kind: str,
        target_kind: str,
        *,
        source_format: str | None = None,
    ) -> None:
        source_widget = getattr(self, f"omnivoice_{source_kind}_text")
        target_widget = getattr(self, f"omnivoice_{target_kind}_text")
        source_document = self.omnivoice_workspace_documents.get(source_kind)
        source_text = source_widget.get("1.0", "end").strip()
        if source_document is None and not source_text:
            return
        parse_kind = source_format or source_kind
        should_parse = (
            source_document is None
            or parse_kind != source_kind
            or self.omnivoice_workspace_source_snapshot.get(source_kind) != source_text
        )
        if should_parse:
            try:
                source_document = (
                    EditableLongformDocument.from_story(source_text)
                    if parse_kind == "stories"
                    else EditableLongformDocument.from_audiobook(source_text)
                )
            except ValueError:
                source_document = None
            else:
                if parse_kind == source_kind:
                    self.omnivoice_workspace_documents[source_kind] = source_document
                    self.omnivoice_workspace_source_snapshot[source_kind] = source_text

        target_document = (
            EditableLongformDocument.from_payload(source_document.to_payload())
            if source_document is not None
            else None
        )
        converted_text = (
            target_document.to_script(target_kind)
            if target_document is not None
            else source_text
        )
        target_widget.delete("1.0", "end")
        target_widget.insert("1.0", converted_text)
        self.omnivoice_workspace_documents[target_kind] = target_document
        self.omnivoice_workspace_source_snapshot[target_kind] = converted_text
        self._set_workspace_cast(target_kind, dict(self._workspace_cast(source_kind)))

        source_project = (
            self.omnivoice_story_project_name
            if source_kind == "stories"
            else self.omnivoice_audiobook_project_name
        ).get().strip()
        target_project = (
            self.omnivoice_story_project_name
            if target_kind == "stories"
            else self.omnivoice_audiobook_project_name
        )
        if source_project:
            target_project.set(source_project)
        if target_kind == "audiobook" and not self.omnivoice_audiobook_title.get().strip():
            self.omnivoice_audiobook_title.set(source_project)

        if target_document is not None:
            self._refresh_workspace_item_tree(target_kind)
            if target_kind == "audiobook":
                self._refresh_audiobook_chapters()
        if converted_text and target_document is not None:
            self._scan_workspace_cast(target_kind)

    def _workspace_cast(self, kind: str) -> dict[str, str]:
        if kind == "stories":
            return self.omnivoice_story_cast
        if kind == "audiobook":
            return self.omnivoice_audiobook_cast
        raise ValueError(f"Unsupported long-form workspace: {kind}")

    def _set_workspace_cast(self, kind: str, cast: dict[str, str]) -> None:
        if kind == "stories":
            self.omnivoice_story_cast = cast
        elif kind == "audiobook":
            self.omnivoice_audiobook_cast = cast
        else:
            raise ValueError(f"Unsupported long-form workspace: {kind}")

    def _build_omnivoice_longform_workspace(
        self,
        parent: ttk.Frame,
        kind: str,
    ) -> ttk.Frame:
        is_story = kind == "stories"
        page = ttk.Frame(parent, padding=8)
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2, minsize=330)
        page.rowconfigure(0, weight=1)
        page.grid(row=0, column=0, sticky="nsew")
        setattr(self, f"omnivoice_{kind}_tab", page)

        editor = ttk.Frame(page, style="Panel.TFrame", padding=8)
        editor.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(1, weight=1)
        tools = ttk.Frame(editor, style="Surface.TFrame")
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tool_specs = [
            ("Mẫu", lambda selected=kind: self._insert_workspace_sample(selected)),
            ("[voice:]", lambda selected=kind: self._insert_workspace_token(selected, "[voice:Người kể] ")),
            ("[pause]", lambda selected=kind: self._insert_workspace_token(selected, "[pause 500ms]")),
            ("Quét vai", lambda selected=kind: self._scan_workspace_cast(selected)),
        ]
        if is_story:
            tool_specs.insert(0, ("Nhập script", self._import_omnivoice_story))
        if not is_story:
            tool_specs.insert(0, ("Nhập sách", self._import_omnivoice_audiobook))
        for column, (label, command) in enumerate(tool_specs):
            button = ttk.Button(tools, text=label, command=command)
            button.grid(row=0, column=column, padx=(0, 5))
            self.omnivoice_mutable_widgets.append(button)

        content_notebook = ttk.Notebook(editor)
        content_notebook.grid(row=1, column=0, sticky="nsew")
        script_page = ttk.Frame(content_notebook)
        script_page.columnconfigure(0, weight=1)
        script_page.rowconfigure(0, weight=1)
        content_notebook.add(script_page, text="Script")
        setattr(self, f"omnivoice_{kind}_content_notebook", content_notebook)
        text_frame = ttk.Frame(script_page, style="Surface.TFrame")
        text_frame.grid(row=0, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        text_widget = tk.Text(
            text_frame,
            wrap="word",
            font="TkTextFont",
            relief="flat",
            padx=10,
            pady=10,
            undo=True,
        )
        text_widget.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text_widget.configure(yscrollcommand=scroll.set)
        setattr(self, f"omnivoice_{kind}_text", text_widget)
        self.omnivoice_mutable_widgets.append(text_widget)
        if is_story:
            build_stories_workspace_editor(self, content_notebook)
        else:
            self._build_audiobook_workspace_editor(content_notebook)

        controls_host = ttk.Frame(page, style="Panel.TFrame")
        controls_host.grid(row=0, column=1, sticky="nsew")
        controls_host.columnconfigure(0, weight=1)
        controls_host.rowconfigure(0, weight=1)
        controls = self._build_omnivoice_scrollable_controls(controls_host)
        controls.configure(padding=12)
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)
        controls.rowconfigure(5 if is_story else 7, weight=1)
        row = 0
        if not is_story:
            row = self._workspace_entry(
                controls, row, "Tên sách", self.omnivoice_audiobook_title
            )
            row = self._workspace_entry(
                controls, row, "Tác giả", self.omnivoice_audiobook_author
            )

        ttk.Label(controls, text="Phân vai", style="Section.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 5)
        )
        row += 1
        tree = ttk.Treeview(
            controls,
            columns=("character", "profile"),
            show="headings",
            height=5,
            selectmode="browse",
        )
        tree.heading("character", text="Nhân vật")
        tree.heading("profile", text="Giọng")
        tree.column("character", width=self._px(115), stretch=True)
        tree.column("profile", width=self._px(150), stretch=True)
        tree.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=(0, 6))
        setattr(self, f"omnivoice_{kind}_cast_tree", tree)
        row += 1
        cast_choice = (
            self.omnivoice_story_cast_choice
            if is_story
            else self.omnivoice_audiobook_cast_choice
        )
        cast_combo = ttk.Combobox(controls, textvariable=cast_choice, state="readonly")
        cast_combo.grid(row=row, column=0, sticky="ew")
        assign = ttk.Button(
            controls,
            text="Gán giọng",
            command=lambda selected=kind: self._assign_workspace_voice(selected),
        )
        assign.grid(row=row, column=1, sticky="ew", padx=(6, 0))
        self.omnivoice_profile_combos.append(cast_combo)
        self.omnivoice_mutable_widgets.extend((cast_combo, assign))
        row += 1

        ttk.Label(controls, text="Giọng mặc định", style="Panel.TLabel").grid(
            row=row, column=0, sticky="w", pady=(7, 0)
        )
        default_combo = ttk.Combobox(
            controls, textvariable=self.omnivoice_profile_choice, state="readonly"
        )
        default_combo.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=(7, 0))
        self.omnivoice_profile_combos.append(default_combo)
        self.omnivoice_mutable_widgets.append(default_combo)
        row += 1
        ttk.Label(controls, text="Ngôn ngữ", style="Panel.TLabel").grid(
            row=row, column=0, sticky="w", pady=3
        )
        language = ttk.Combobox(
            controls,
            textvariable=self.omnivoice_language,
            values=self.omnivoice_language_values,
            state="normal",
        )
        language.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=3)
        self.omnivoice_editable_combos.append(language)
        self.omnivoice_language_combos.append(language)
        self.omnivoice_mutable_widgets.append(language)
        row += 1
        project_variable = (
            self.omnivoice_story_project_name
            if is_story
            else self.omnivoice_audiobook_project_name
        )
        row = self._workspace_entry(controls, row, "Tên project", project_variable)
        stems = ttk.Checkbutton(
            controls,
            text="Xuất từng đoạn WAV (stems)",
            variable=(
                self.omnivoice_story_export_stems
                if is_story
                else self.omnivoice_audiobook_export_stems
            ),
        )
        stems.grid(row=row, column=0, columnspan=2, sticky="w", pady=3)
        self.omnivoice_mutable_widgets.append(stems)
        row += 1
        if not is_story:
            m4b = ttk.Checkbutton(
                controls,
                text="Xuất sách nói M4B có chương",
                variable=self.omnivoice_audiobook_export_m4b,
            )
            m4b.grid(row=row, column=0, columnspan=2, sticky="w", pady=3)
            self.omnivoice_mutable_widgets.append(m4b)
            row += 1
        row = self._build_workspace_output_row(controls, row)

        actions = ttk.Frame(controls, style="Surface.TFrame")
        actions.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        actions.columnconfigure((0, 1), weight=1)
        generate = ttk.Button(
            actions,
            text="Tạo truyện" if is_story else "Tạo sách nói",
            style="Accent.TButton",
            command=lambda selected=kind: self._start_omnivoice_workspace(selected),
        )
        generate.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        stop = ttk.Button(actions, text="Dừng", command=self._stop_omnivoice, state="disabled")
        stop.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        play = ttk.Button(actions, text="Nghe", command=self._play_omnivoice_result, state="disabled")
        play.grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=(6, 0))
        open_button = ttk.Button(
            actions, text="Mở output", command=self._open_omnivoice_output, state="disabled"
        )
        open_button.grid(row=1, column=1, sticky="ew", padx=(3, 0), pady=(6, 0))
        row += 1
        progress = ttk.Progressbar(controls, mode="indeterminate")
        progress.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(9, 0))
        self.omnivoice_generate_buttons.append(generate)
        self.omnivoice_stop_buttons.append(stop)
        self.omnivoice_play_buttons.append(play)
        self.omnivoice_open_buttons.append(open_button)
        self.omnivoice_progress_bars.append(progress)
        return page

    def _workspace_entry(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.Variable,
    ) -> int:
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(
            row=row, column=0, sticky="w", pady=3
        )
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=3)
        self.omnivoice_mutable_widgets.append(entry)
        return row + 1

    def _build_workspace_output_row(self, parent: ttk.Frame, row: int) -> int:
        ttk.Label(parent, text="Thư mục output", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        row += 1
        entry = ttk.Entry(parent, textvariable=self.omnivoice_output_dir)
        entry.grid(row=row, column=0, sticky="ew", pady=3)
        browse = ttk.Button(parent, text="Chọn", command=self._browse_omnivoice_output)
        browse.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=3)
        self.omnivoice_mutable_widgets.extend((entry, browse))
        return row + 1

    def _build_omnivoice_gallery_workspace(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=8)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        notebook.add(page, text="Gallery")
        self.omnivoice_gallery_tab = page
        self.omnivoice_gallery_notebook = ttk.Notebook(page)
        self.omnivoice_gallery_notebook.grid(row=0, column=0, sticky="nsew")

        presets = ttk.Frame(self.omnivoice_gallery_notebook, padding=10)
        presets.columnconfigure(0, weight=3)
        presets.columnconfigure(1, weight=2)
        presets.rowconfigure(1, weight=1)
        self.omnivoice_gallery_notebook.add(presets, text="Presets")
        filters = ttk.Frame(presets)
        filters.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        filters.columnconfigure(0, weight=1)
        search = ttk.Entry(filters, textvariable=self.omnivoice_gallery_search)
        search.grid(row=0, column=0, sticky="ew")
        category = ttk.Combobox(
            filters,
            textvariable=self.omnivoice_gallery_category,
            values=("Tất cả", *voice_archetype_categories()),
            state="readonly",
            width=18,
        )
        category.grid(row=0, column=1, padx=(7, 0))
        favorites_only = ttk.Checkbutton(
            filters,
            text="Yêu thích",
            variable=self.omnivoice_gallery_favorites_only,
            command=self._reset_omnivoice_gallery_page,
        )
        favorites_only.grid(row=0, column=2, padx=(7, 0))
        previous = ttk.Button(
            filters,
            text="‹",
            width=3,
            command=lambda: self._change_omnivoice_gallery_page(-1),
        )
        previous.grid(row=0, column=3, padx=(7, 0))
        ttk.Label(filters, textvariable=self.omnivoice_gallery_page_status).grid(
            row=0, column=4, padx=5
        )
        following = ttk.Button(
            filters,
            text="›",
            width=3,
            command=lambda: self._change_omnivoice_gallery_page(1),
        )
        following.grid(row=0, column=5)
        self.omnivoice_mutable_widgets.extend(
            (search, category, favorites_only, previous, following)
        )
        search.bind("<KeyRelease>", lambda _event: self._reset_omnivoice_gallery_page())
        category.bind(
            "<<ComboboxSelected>>", lambda _event: self._reset_omnivoice_gallery_page()
        )

        tree_frame = ttk.Frame(presets, style="Panel.TFrame", padding=7)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 9))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.omnivoice_gallery_tree = ttk.Treeview(
            tree_frame,
            columns=("favorite", "name", "use_case", "language"),
            show="headings",
            selectmode="browse",
        )
        for column, label, width in (
            ("favorite", "★", 42),
            ("name", "Giọng", 190),
            ("use_case", "Mục đích", 110),
            ("language", "Ngôn ngữ", 85),
        ):
            self.omnivoice_gallery_tree.heading(column, text=label)
            self.omnivoice_gallery_tree.column(
                column, width=self._px(width), stretch=True
            )
        self.omnivoice_gallery_tree.grid(row=0, column=0, sticky="nsew")
        self.omnivoice_gallery_tree.bind(
            "<<TreeviewSelect>>", lambda _event: self._show_omnivoice_archetype()
        )

        details = ttk.Frame(presets, style="Panel.TFrame", padding=10)
        details.grid(row=1, column=1, sticky="nsew")
        details.columnconfigure(0, weight=1)
        details.rowconfigure(1, weight=1)
        ttk.Label(details, text="Thiết lập giọng", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.omnivoice_gallery_details = tk.Text(
            details, wrap="word", height=12, font="TkTextFont", state="disabled"
        )
        self.omnivoice_gallery_details.grid(row=1, column=0, sticky="nsew", pady=7)
        use = ttk.Button(
            details,
            text="Dùng trong Voice Design",
            style="Accent.TButton",
            command=self._use_omnivoice_archetype,
        )
        use.grid(row=2, column=0, sticky="ew")
        self.omnivoice_mutable_widgets.append(use)
        gallery_actions = ttk.Frame(details, style="Surface.TFrame")
        gallery_actions.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        gallery_actions.columnconfigure((0, 1, 2), weight=1)
        preview = ttk.Button(
            gallery_actions,
            text="Nghe thử",
            command=self._preview_omnivoice_archetype,
        )
        preview.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        favorite = ttk.Button(
            gallery_actions,
            text="Yêu thích",
            command=self._toggle_omnivoice_archetype_favorite,
        )
        favorite.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        create_profile = ttk.Button(
            gallery_actions,
            text="Tạo profile",
            command=self._materialize_omnivoice_archetype,
        )
        create_profile.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        self.omnivoice_mutable_widgets.extend((preview, favorite, create_profile))

        self._build_omnivoice_library_tab(self.omnivoice_gallery_notebook)
        self.omnivoice_gallery_notebook.tab(self.omnivoice_library_tab, text="Giọng đã lưu")
        self.omnivoice_auto_tab = self._build_omnivoice_studio_page(
            self.omnivoice_gallery_notebook, "Auto Voice", AUTO_MODE
        )
        self._build_omnivoice_batch_tab(self.omnivoice_gallery_notebook)
        self.omnivoice_gallery_notebook.tab(self.omnivoice_batch_tab, text="Batch")
        self._build_omnivoice_lora_tab(self.omnivoice_gallery_notebook)
        self._build_omnivoice_runtime_tab(self.omnivoice_gallery_notebook)
        self.omnivoice_gallery_notebook.tab(self.omnivoice_runtime_tab, text="Runtime")
        self._build_omnivoice_history_tab(self.omnivoice_gallery_notebook)
        self._refresh_omnivoice_gallery()

    def _build_omnivoice_transcripts_workspace(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=12)
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2)
        page.rowconfigure(1, weight=1)
        notebook.add(page, text="Transcripts")
        self.omnivoice_transcripts_tab = page
        search = ttk.Entry(page, textvariable=self.omnivoice_transcript_search)
        search.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        search.bind("<KeyRelease>", lambda _event: self._refresh_omnivoice_transcripts())
        self.omnivoice_mutable_widgets.append(search)

        tree_frame = ttk.Frame(page, style="Panel.TFrame", padding=7)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 9))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.omnivoice_transcript_tree = ttk.Treeview(
            tree_frame,
            columns=("source", "language", "created"),
            show="headings",
            selectmode="browse",
        )
        for column, label, width in (
            ("source", "Nguồn", 230),
            ("language", "Ngôn ngữ", 90),
            ("created", "Ngày tạo", 150),
        ):
            self.omnivoice_transcript_tree.heading(column, text=label)
            self.omnivoice_transcript_tree.column(
                column, width=self._px(width), stretch=True
            )
        self.omnivoice_transcript_tree.grid(row=0, column=0, sticky="nsew")
        self.omnivoice_transcript_tree.bind(
            "<<TreeviewSelect>>", lambda _event: self._show_omnivoice_transcript()
        )

        details = ttk.Frame(page, style="Panel.TFrame", padding=9)
        details.grid(row=1, column=1, sticky="nsew")
        details.columnconfigure(0, weight=1)
        details.rowconfigure(0, weight=1)
        self.omnivoice_transcript_details = tk.Text(
            details, wrap="word", font="TkTextFont", state="disabled"
        )
        self.omnivoice_transcript_details.grid(row=0, column=0, sticky="nsew")
        actions = ttk.Frame(details, style="Surface.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        actions.columnconfigure((0, 1), weight=1)
        for index, (label, command) in enumerate(
            (
                ("Đưa sang Dubbing", self._use_transcript_in_dubbing),
                ("Xuất SRT", self._export_omnivoice_transcript),
                ("Sao chép", self._copy_omnivoice_transcript),
                ("Xuất tất cả", self._export_all_omnivoice_transcripts),
                ("Xóa", self._delete_omnivoice_transcript),
                ("Xóa lịch sử", self._clear_omnivoice_transcripts),
            )
        ):
            button = ttk.Button(actions, text=label, command=command)
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=3, pady=3)
            self.omnivoice_mutable_widgets.append(button)
        self._refresh_omnivoice_transcripts()

    def _build_omnivoice_history_tab(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=9)
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2)
        page.rowconfigure(1, weight=1)
        notebook.add(page, text="Lịch sử tạo")
        filters = ttk.Frame(page)
        filters.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        filters.columnconfigure(0, weight=1)
        search = ttk.Entry(filters, textvariable=self.omnivoice_history_search)
        search.grid(row=0, column=0, sticky="ew")
        workspace = ttk.Combobox(
            filters,
            textvariable=self.omnivoice_history_workspace,
            values=(
                "Tất cả",
                "clone",
                "design",
                "auto",
                "batch",
                "dubbing",
                "stories",
                "audiobook",
            ),
            state="readonly",
            width=14,
        )
        workspace.grid(row=0, column=1, padx=(7, 0))
        starred = ttk.Checkbutton(
            filters,
            text="Đã đánh dấu",
            variable=self.omnivoice_history_starred_only,
            command=self._refresh_omnivoice_history,
        )
        starred.grid(row=0, column=2, padx=(7, 0))
        search.bind("<KeyRelease>", lambda _event: self._refresh_omnivoice_history())
        workspace.bind(
            "<<ComboboxSelected>>", lambda _event: self._refresh_omnivoice_history()
        )
        self.omnivoice_mutable_widgets.extend((search, workspace, starred))

        tree_frame = ttk.Frame(page, style="Panel.TFrame", padding=6)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            tree_frame,
            columns=("star", "workspace", "title", "created"),
            show="headings",
            selectmode="browse",
        )
        for column, label, width in (
            ("star", "★", 40),
            ("workspace", "Tính năng", 90),
            ("title", "Tên", 230),
            ("created", "Ngày tạo", 145),
        ):
            tree.heading(column, text=label)
            tree.column(
                column, width=self._px(width), stretch=column == "title"
            )
        tree.grid(row=0, column=0, sticky="nsew")
        tree.bind("<<TreeviewSelect>>", lambda _event: self._show_omnivoice_history())
        self.omnivoice_history_tree = tree

        details = ttk.Frame(page, style="Panel.TFrame", padding=9)
        details.grid(row=1, column=1, sticky="nsew")
        details.columnconfigure(0, weight=1)
        details.rowconfigure(0, weight=1)
        self.omnivoice_history_details = tk.Text(
            details, wrap="word", state="disabled", font="TkTextFont"
        )
        self.omnivoice_history_details.grid(row=0, column=0, sticky="nsew")
        actions = ttk.Frame(details, style="Surface.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        actions.columnconfigure((0, 1, 2), weight=1)
        for column, (label, command) in enumerate(
            (
                ("Mở file", self._open_omnivoice_history),
                ("Đánh dấu", self._toggle_omnivoice_history_star),
                ("Xóa", self._delete_omnivoice_history),
            )
        ):
            button = ttk.Button(actions, text=label, command=command)
            button.grid(row=0, column=column, sticky="ew", padx=2)
            self.omnivoice_mutable_widgets.append(button)
        self._refresh_omnivoice_history()

    def _insert_workspace_sample(self, kind: str) -> None:
        widget = getattr(self, f"omnivoice_{kind}_text")
        widget.delete("1.0", "end")
        widget.insert("1.0", _STORY_SAMPLE if kind == "stories" else _AUDIOBOOK_SAMPLE)
        self._scan_workspace_cast(kind)

    def _insert_workspace_token(self, kind: str, token: str) -> None:
        widget = getattr(self, f"omnivoice_{kind}_text")
        widget.insert("insert", token)
        widget.focus_set()

    def _import_omnivoice_audiobook(self) -> None:
        selected = filedialog.askopenfilename(
            title="Nhập sách",
            filetypes=[
                ("Sách và văn bản", "*.txt *.md *.epub *.pdf"),
                ("Tất cả file", "*.*"),
            ],
        )
        if not selected:
            return
        try:
            content = load_audiobook_source(Path(selected))
        except (OSError, RuntimeError, ValueError) as error:
            messagebox.showerror("Không đọc được sách", str(error))
            return
        self.omnivoice_audiobook_text.delete("1.0", "end")
        self.omnivoice_audiobook_text.insert("1.0", content)
        if not self.omnivoice_audiobook_title.get().strip():
            self.omnivoice_audiobook_title.set(Path(selected).stem)
        self._scan_workspace_cast("audiobook")

    def _import_omnivoice_story(self) -> None:
        selected = filedialog.askopenfilename(
            title="Nhập script truyện",
            filetypes=[("Script", "*.txt *.md"), ("Tất cả file", "*.*")],
        )
        if not selected:
            return
        try:
            content = Path(selected).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Không đọc được script", str(error))
            return
        self.omnivoice_stories_text.delete("1.0", "end")
        self.omnivoice_stories_text.insert("1.0", content)
        self.omnivoice_story_project_name.set(Path(selected).stem)
        self.omnivoice_workspace_documents["stories"] = None
        self._scan_workspace_cast("stories")

    def _workspace_plan(self, kind: str) -> LongformPlan:
        return self._load_workspace_document(kind)

    def _scan_workspace_cast(self, kind: str) -> None:
        try:
            plan = self._workspace_plan(kind)
        except ValueError as error:
            messagebox.showerror("Nội dung chưa hợp lệ", str(error))
            return
        tree: ttk.Treeview = getattr(self, f"omnivoice_{kind}_cast_tree")
        cast = self._workspace_cast(kind)
        tree.delete(*tree.get_children())
        for index, character in enumerate(plan.voice_names):
            profile_id = cast.get(character, "")
            profile_name = next(
                (
                    profile.display_name
                    for profile in self.omnivoice_profiles
                    if profile.profile_id == profile_id
                ),
                "Giọng mặc định",
            )
            tree.insert("", "end", iid=f"role-{index}", values=(character, profile_name))

    def _assign_workspace_voice(self, kind: str) -> None:
        tree: ttk.Treeview = getattr(self, f"omnivoice_{kind}_cast_tree")
        selection = tree.selection()
        if not selection:
            return
        character = str(tree.item(selection[0], "values")[0])
        choice = (
            self.omnivoice_story_cast_choice.get()
            if kind == "stories"
            else self.omnivoice_audiobook_cast_choice.get()
        )
        profile = self._omnivoice_profile_by_label.get(choice)
        cast = self._workspace_cast(kind)
        if profile is None:
            cast.pop(character, None)
        else:
            cast[character] = profile.profile_id
        self._scan_workspace_cast(kind)

    def _start_omnivoice_workspace(
        self,
        kind: str,
        resume_project_dir: Path | None = None,
    ) -> None:
        if self._active_task is not None:
            return
        if not self._require_omnivoice_runtime():
            return
        try:
            plan = self._workspace_plan(kind)
            project = (
                self.omnivoice_story_project_name.get().strip()
                if kind == "stories"
                else self.omnivoice_audiobook_project_name.get().strip()
            ) or f"omnivoice-{kind}"
            options = self._workspace_options(plan, project)
        except (OSError, ValueError) as error:
            messagebox.showerror("Thiết lập chưa hợp lệ", str(error))
            return
        cast = dict(self._workspace_cast(kind))
        self._start_omnivoice_thread(
            f"omnivoice_{kind}",
            self._run_omnivoice_workspace,
            (kind, options, plan, cast, resume_project_dir),
            f"omnivoice-{kind}",
        )

    def _start_longform_item_preview(
        self,
        kind: str,
        item: EditableLongformItem,
    ) -> None:
        if self._active_task is not None or not self._require_omnivoice_runtime():
            return
        try:
            plan = EditableLongformDocument(
                items=[replace(item, pause_after_ms=0)],
                chapters=[item.chapter],
            ).to_plan()
            options = self._workspace_options(plan, f"preview-{item.item_id}")
        except (OSError, ValueError) as error:
            messagebox.showerror("Không thể nghe thử", str(error))
            return
        cast = dict(self._workspace_cast(kind))
        self._start_omnivoice_thread(
            f"omnivoice_{kind}_preview",
            self._run_omnivoice_workspace,
            (f"{kind}_preview:{item.item_id}", options, plan, cast),
            f"omnivoice-{kind}-preview",
        )

    def start_omnivoice_dubbing(self) -> None:
        if self._active_task is not None:
            return
        draft = self.subtitle_draft
        if draft is None:
            messagebox.showinfo(
                "Chưa có phụ đề",
                "Hãy chọn video và bấm Create Subtitles trước. Bản dịch sẽ được dùng để lồng tiếng.",
            )
            return
        if not self._require_omnivoice_runtime():
            return
        try:
            if self.omnivoice_dubbing_segments:
                if self._selected_dubbing_segment() is not None:
                    self._apply_selected_dubbing_segment()
                plan = plan_dubbing_segments(tuple(self.omnivoice_dubbing_segments))
            else:
                subtitle_text = (
                    self.translated_subtitle_text.get("1.0", "end").strip()
                    if draft.translated_cues is not None
                    else self.source_subtitle_text.get("1.0", "end").strip()
                )
                cues = parse_srt(subtitle_text)
                plan = plan_dubbing_cues(cues)
            options = self._workspace_options(plan, f"{draft.project_name}-dubbing")
            options = replace(options, language=draft.script_language or options.language)
        except (OSError, ValueError) as error:
            messagebox.showerror("Không thể lồng tiếng", str(error))
            return
        self._start_omnivoice_thread(
            "omnivoice_dub",
            self._run_omnivoice_workspace,
            ("dubbing", options, plan, dict(self.omnivoice_dubbing_cast)),
            "omnivoice-dubbing",
        )

    def _start_audiobook_chapter_preview(
        self,
        chapter: str,
        plan: LongformPlan,
    ) -> None:
        if self._active_task is not None or not self._require_omnivoice_runtime():
            return
        try:
            options = self._workspace_options(plan, f"preview-{chapter}")
        except (OSError, ValueError) as error:
            messagebox.showerror("Không thể nghe thử chương", str(error))
            return
        self._start_omnivoice_thread(
            "omnivoice_audiobook_chapter_preview",
            self._run_omnivoice_workspace,
            ("audiobook_chapter_preview", options, plan, dict(self.omnivoice_audiobook_cast)),
            "omnivoice-audiobook-chapter-preview",
        )

    def _start_dubbing_segment_preview(self, segment) -> None:
        if self._active_task is not None or not self._require_omnivoice_runtime():
            return
        try:
            plan = plan_dubbing_segments((segment,))
            options = self._workspace_options(plan, f"preview-{segment.segment_id}")
            draft = self.subtitle_draft
            if draft is not None:
                options = replace(options, language=draft.script_language or options.language)
        except (OSError, ValueError) as error:
            messagebox.showerror("Khong the nghe thu", str(error))
            return
        self._start_omnivoice_thread(
            "omnivoice_dubbing_preview",
            self._run_omnivoice_workspace,
            ("dubbing_preview", options, plan, dict(self.omnivoice_dubbing_cast)),
            "omnivoice-dubbing-preview",
        )

    def _workspace_options(
        self,
        plan: LongformPlan,
        project_name: str,
    ) -> OmniVoiceGenerationOptions:
        first_text = next(span.text for span in plan.spans if span.text)
        mode = CLONE_MODE if self._selected_omnivoice_profile() is not None else AUTO_MODE
        return self._omnivoice_options(
            mode,
            first_text,
            bulk=True,
            project_name=project_name,
        )

    def _run_omnivoice_workspace(
        self,
        kind: str,
        options: OmniVoiceGenerationOptions,
        plan: LongformPlan,
        cast: dict[str, str],
        resume_project_dir: Path | None = None,
    ) -> None:
        try:
            result = render_longform_plan(
                options,
                plan,
                self.omnivoice_client,
                profiles=tuple(self.omnivoice_profiles),
                cast_map=cast,
                gap_ms=0 if kind == "dubbing" else 250,
                export_mp3=bool(self.omnivoice_export_mp3.get()),
                export_m4b=(
                    kind == "audiobook" and bool(self.omnivoice_audiobook_export_m4b.get())
                ),
                export_stems=(
                    bool(self.omnivoice_story_export_stems.get())
                    if kind == "stories"
                    else bool(self.omnivoice_audiobook_export_stems.get())
                    if kind == "audiobook"
                    else False
                ),
                title=self.omnivoice_audiobook_title.get() if kind == "audiobook" else "",
                author=self.omnivoice_audiobook_author.get() if kind == "audiobook" else "",
                cover_path=(
                    Path(self.omnivoice_audiobook_cover.get()).expanduser()
                    if kind == "audiobook" and self.omnivoice_audiobook_cover.get().strip()
                    else None
                ),
                progress=lambda message: self.events.put(("omnivoice_progress", message)),
                resume_project_dir=resume_project_dir,
            )
        except Exception as error:
            event = "omnivoice_cancelled" if self._omnivoice_cancel_requested else "omnivoice_error"
            self.events.put((event, error))
        else:
            self.events.put(("omnivoice_workspace_done", (kind, result)))

    def _require_omnivoice_runtime(self) -> bool:
        status = inspect_runtime(self.omnivoice_runtime)
        if status.installed:
            return True
        messagebox.showerror("OmniVoice chưa được cài", status.message)
        self._select_omnivoice_runtime()
        return False

    def _select_omnivoice_runtime(self) -> None:
        self.voice_feature_notebook.select(self.omnivoice_gallery_tab)
        self.omnivoice_gallery_notebook.select(self.omnivoice_runtime_tab)

    def _finish_omnivoice_workspace(
        self,
        kind: str,
        result: LongformWorkspaceResult,
    ) -> None:
        self.omnivoice_last_result = None
        self.omnivoice_last_batch_result = None
        self.omnivoice_workspace_result = result
        if kind == "dubbing":
            self.omnivoice_last_dub_result = result
            if hasattr(self, "dub_editor_button"):
                self.dub_editor_button.configure(state="normal")
        elif kind == "dubbing_preview":
            selected = self._selected_dubbing_segment()
            if selected is not None:
                self._replace_dubbing_segment(
                    replace(selected, preview_path=str(result.wav_path))
                )
            try:
                os.startfile(result.wav_path)
            except OSError:
                pass
        elif "_preview:" in kind:
            workspace, item_id = kind.split("_preview:", 1)
            self._mark_workspace_item_preview(workspace, item_id, result.wav_path)
            try:
                os.startfile(result.wav_path)
            except OSError:
                pass
        elif kind.endswith("_preview"):
            try:
                os.startfile(result.wav_path)
            except OSError:
                pass
        self.omnivoice_job_status.set("Hoàn tất")
        self.status.set("Done")
        for button in self.omnivoice_open_buttons:
            button.configure(state="normal")
        for button in self.omnivoice_play_buttons:
            button.configure(state="normal")
        self._append_omnivoice_log(f"Workspace {kind}: {result.project_dir}")
        self._append_omnivoice_log(f"WAV: {result.wav_path}")
        self._append_omnivoice_log(f"SRT: {result.srt_path}")
        if result.m4b_path:
            self._append_omnivoice_log(f"M4B: {result.m4b_path}")
        if result.stems_dir:
            self._append_omnivoice_log(f"Stems: {result.stems_dir}")
        for warning in result.warnings:
            self._append_omnivoice_log(f"Cảnh báo: {warning}")

        if kind.endswith("_preview") or "_preview:" in kind:
            return
        self.omnivoice_workspace_repository.add_history(
            workspace=kind,
            title=result.project_dir.name,
            summary=f"{len(result.item_results)} đoạn đã tạo",
            artifact_path=str(result.m4b_path or result.mp3_path or result.wav_path),
            metadata={
                "project_dir": str(result.project_dir),
                "wav_path": str(result.wav_path),
                "srt_path": str(result.srt_path),
                "mp3_path": str(result.mp3_path or ""),
                "m4b_path": str(result.m4b_path or ""),
                "stems_dir": str(result.stems_dir or ""),
            },
        )
        self._refresh_omnivoice_history()

    def send_dubbing_to_editor(self) -> None:
        draft = self.subtitle_draft
        result = self.omnivoice_last_dub_result
        if draft is None or result is None:
            return
        self.import_editor_bundle(draft.source_video, result.wav_path, result.srt_path)

    def _refresh_omnivoice_gallery(self) -> None:
        if not hasattr(self, "omnivoice_gallery_tree"):
            return
        category = self.omnivoice_gallery_category.get()
        items = list_voice_archetypes(
            self.omnivoice_gallery_search.get(),
            "" if category == "Tất cả" else category,
        )
        if self.omnivoice_gallery_favorites_only.get():
            items = tuple(
                item for item in items if item.archetype_id in self.omnivoice_gallery_favorites
            )
        page_size = 120
        page_count = max(1, (len(items) + page_size - 1) // page_size)
        self.omnivoice_gallery_page = max(0, min(self.omnivoice_gallery_page, page_count - 1))
        start = self.omnivoice_gallery_page * page_size
        items = items[start : start + page_size]
        self.omnivoice_gallery_page_status.set(
            f"Trang {self.omnivoice_gallery_page + 1}/{page_count}"
        )
        self.omnivoice_gallery_tree.delete(*self.omnivoice_gallery_tree.get_children())
        for item in items:
            self.omnivoice_gallery_tree.insert(
                "",
                "end",
                iid=item.archetype_id,
                values=(
                    "★" if item.archetype_id in self.omnivoice_gallery_favorites else "",
                    item.name,
                    item.use_case,
                    item.language,
                ),
            )
        if items:
            self.omnivoice_gallery_tree.selection_set(items[0].archetype_id)
            self._show_omnivoice_archetype()

    def _reset_omnivoice_gallery_page(self) -> None:
        self.omnivoice_gallery_page = 0
        self._refresh_omnivoice_gallery()

    def _change_omnivoice_gallery_page(self, delta: int) -> None:
        self.omnivoice_gallery_page = max(0, self.omnivoice_gallery_page + int(delta))
        self._refresh_omnivoice_gallery()

    def _selected_omnivoice_archetype(self) -> VoiceArchetype | None:
        selection = self.omnivoice_gallery_tree.selection()
        if not selection:
            return None
        selected_id = selection[0]
        return next(
            (item for item in list_voice_archetypes() if item.archetype_id == selected_id),
            None,
        )

    def _show_omnivoice_archetype(self) -> None:
        item = self._selected_omnivoice_archetype()
        if item is None:
            return
        text = (
            f"{item.name}\n\nMục đích: {item.use_case}\nNgôn ngữ: {item.language}\n\n"
            f"Thiết kế:\n{item.instruct}\n\nCâu mẫu:\n{item.sample_text}"
        )
        self.omnivoice_gallery_details.configure(state="normal")
        self.omnivoice_gallery_details.delete("1.0", "end")
        self.omnivoice_gallery_details.insert("1.0", text)
        self.omnivoice_gallery_details.configure(state="disabled")

    def _use_omnivoice_archetype(self) -> None:
        item = self._selected_omnivoice_archetype()
        if item is None:
            return
        for variable in (
            self.omnivoice_design_gender,
            self.omnivoice_design_age,
            self.omnivoice_design_pitch,
            self.omnivoice_design_style,
            self.omnivoice_design_accent,
            self.omnivoice_design_dialect,
        ):
            variable.set("")
        self.omnivoice_custom_instruct.delete("1.0", "end")
        self.omnivoice_custom_instruct.insert("1.0", item.instruct)
        design_text = self.omnivoice_text_widgets[DESIGN_MODE]
        design_text.delete("1.0", "end")
        design_text.insert("1.0", item.sample_text)
        self.omnivoice_language.set(item.language)
        self.voice_feature_notebook.select(self.omnivoice_design_tab)

    def _preview_omnivoice_archetype(self) -> None:
        item = self._selected_omnivoice_archetype()
        if item is None:
            return
        self._use_omnivoice_archetype()
        self._start_omnivoice_generation(DESIGN_MODE)

    def _toggle_omnivoice_archetype_favorite(self) -> None:
        item = self._selected_omnivoice_archetype()
        if item is None:
            return
        if item.archetype_id in self.omnivoice_gallery_favorites:
            self.omnivoice_gallery_favorites.remove(item.archetype_id)
        else:
            self.omnivoice_gallery_favorites.add(item.archetype_id)
        project = self.omnivoice_workspace_repository.save_project(
            workspace="gallery",
            name="favorites",
            project_id=self.omnivoice_gallery_favorites_project_id,
            payload={"ids": sorted(self.omnivoice_gallery_favorites)},
        )
        self.omnivoice_gallery_favorites_project_id = project.project_id
        self._refresh_omnivoice_gallery()

    def _materialize_omnivoice_archetype(self) -> None:
        item = self._selected_omnivoice_archetype()
        if item is None:
            return
        name = simpledialog.askstring(
            "Tạo profile từ Gallery",
            "Tên profile:",
            initialvalue=item.name,
            parent=self.root,
        )
        if not name or not name.strip():
            return
        self._use_omnivoice_archetype()
        self.omnivoice_save_profile_name.set(name.strip())
        self._start_omnivoice_generation(DESIGN_MODE)

    def _selected_omnivoice_history(self):
        if not hasattr(self, "omnivoice_history_tree"):
            return None
        selection = self.omnivoice_history_tree.selection()
        if not selection:
            return None
        return next(
            (
                item
                for item in self.omnivoice_workspace_repository.list_history()
                if item.history_id == selection[0]
            ),
            None,
        )

    def _refresh_omnivoice_history(self) -> None:
        if not hasattr(self, "omnivoice_history_tree"):
            return
        workspace = self.omnivoice_history_workspace.get()
        items = self.omnivoice_workspace_repository.search_history(
            self.omnivoice_history_search.get(),
            workspace="" if workspace == "Tất cả" else workspace,
            starred_only=bool(self.omnivoice_history_starred_only.get()),
        )
        self.omnivoice_history_tree.delete(*self.omnivoice_history_tree.get_children())
        for item in items:
            self.omnivoice_history_tree.insert(
                "",
                "end",
                iid=item.history_id,
                values=(
                    "★" if item.starred else "",
                    item.workspace,
                    item.title,
                    item.created_at[:19].replace("T", " "),
                ),
            )

    def _show_omnivoice_history(self) -> None:
        item = self._selected_omnivoice_history()
        if item is None:
            return
        details = (
            f"{item.title}\n\nTính năng: {item.workspace}\n"
            f"Tạo lúc: {item.created_at[:19].replace('T', ' ')}\n"
            f"File: {item.artifact_path}\n\n{item.summary}"
        )
        self.omnivoice_history_details.configure(state="normal")
        self.omnivoice_history_details.delete("1.0", "end")
        self.omnivoice_history_details.insert("1.0", details)
        self.omnivoice_history_details.configure(state="disabled")

    def _open_omnivoice_history(self) -> None:
        item = self._selected_omnivoice_history()
        if item is None:
            return
        path = Path(item.artifact_path)
        target = path if path.exists() else Path(str(item.metadata.get("project_dir") or ""))
        if target.exists():
            os.startfile(target)
        else:
            messagebox.showwarning("Lịch sử tạo", "File này không còn tồn tại trên máy.")

    def _toggle_omnivoice_history_star(self) -> None:
        item = self._selected_omnivoice_history()
        if item is None:
            return
        self.omnivoice_workspace_repository.set_history_starred(
            item.history_id, not item.starred
        )
        self._refresh_omnivoice_history()

    def _delete_omnivoice_history(self) -> None:
        item = self._selected_omnivoice_history()
        if item is None:
            return
        self.omnivoice_workspace_repository.delete_history(item.history_id)
        self._refresh_omnivoice_history()

    def record_omnivoice_generation_result(self, result) -> None:
        payload = read_json(result.manifest_path)
        options = payload.get("options") if isinstance(payload, dict) else {}
        options = options if isinstance(options, dict) else {}
        mode = str(options.get("mode") or "voice")
        text = str(options.get("text") or "")
        artifact = result.mp3_path or result.wav_path
        self.omnivoice_workspace_repository.add_history(
            workspace=mode,
            title=result.project_dir.name,
            summary=text[:240],
            artifact_path=str(artifact),
            metadata={
                "project_dir": str(result.project_dir),
                "profile_id": result.profile_id,
                "language": str(options.get("language") or ""),
            },
        )
        self._refresh_omnivoice_history()

    def record_omnivoice_batch_result(self, result) -> None:
        artifact = result.combined_mp3_path or result.combined_wav_path
        if artifact is None and result.item_results:
            artifact = result.item_results[0].wav_path
        self.omnivoice_workspace_repository.add_history(
            workspace="batch",
            title=result.project_dir.name,
            summary=f"{len(result.item_results)} mục đã tạo",
            artifact_path=str(artifact or result.project_dir),
            metadata={"project_dir": str(result.project_dir)},
        )
        self._refresh_omnivoice_history()

    def record_omnivoice_transcript(self, draft: VideoSubtitleDraft) -> None:
        try:
            self.omnivoice_transcript_store.add(
                text=draft.script_text,
                language=draft.script_language,
                source_path=str(draft.source_video),
                source_srt=draft.source_srt_text,
                translated_srt=draft.translated_srt_text,
            )
        except OSError as error:
            self._append_omnivoice_log(f"Không lưu được transcript: {error}")
        self._refresh_omnivoice_transcripts()

    def _refresh_omnivoice_transcripts(self) -> None:
        if not hasattr(self, "omnivoice_transcript_tree"):
            return
        entries = self.omnivoice_transcript_store.search(self.omnivoice_transcript_search.get())
        self.omnivoice_transcript_tree.delete(*self.omnivoice_transcript_tree.get_children())
        for entry in entries:
            source = Path(entry.source_path).name or "Không rõ"
            created = entry.created_at[:19].replace("T", " ")
            self.omnivoice_transcript_tree.insert(
                "", "end", iid=entry.entry_id, values=(source, entry.language, created)
            )

    def _selected_omnivoice_transcript(self) -> TranscriptEntry | None:
        selection = self.omnivoice_transcript_tree.selection()
        if not selection:
            return None
        entry_id = selection[0]
        return next(
            (entry for entry in self.omnivoice_transcript_store.list() if entry.entry_id == entry_id),
            None,
        )

    def _show_omnivoice_transcript(self) -> None:
        entry = self._selected_omnivoice_transcript()
        if entry is None:
            return
        self.omnivoice_transcript_details.configure(state="normal")
        self.omnivoice_transcript_details.delete("1.0", "end")
        self.omnivoice_transcript_details.insert("1.0", entry.text)
        self.omnivoice_transcript_details.configure(state="disabled")

    def _use_transcript_in_dubbing(self) -> None:
        entry = self._selected_omnivoice_transcript()
        if entry is None:
            return
        try:
            source_cues = tuple(parse_srt(entry.source_srt))
            translated_cues = (
                tuple(parse_srt(entry.translated_srt)) if entry.translated_srt else None
            )
        except ValueError as error:
            messagebox.showerror("Transcript không hợp lệ", str(error))
            return
        source_video = Path(entry.source_path).expanduser()
        draft = VideoSubtitleDraft(
            source_video=source_video,
            project_name=source_video.stem or "transcript-dubbing",
            audio_path=source_video,
            source_language="auto",
            target_language=entry.language,
            whisper_model="history",
            ai_provider="history",
            ai_model="history",
            ai_base_url="",
            source_cues=source_cues,
            translated_cues=translated_cues,
            warnings=([] if source_video.is_file() else ["Video nguồn trong lịch sử không còn tồn tại."]),
        )
        self._replace_subtitle_draft(draft)
        self._load_subtitle_draft(draft)
        self.load_dubbing_segments_from_draft(draft)
        self._set_busy(False)
        self.voice_feature_notebook.select(self.classic_voice_tab)

    def _export_omnivoice_transcript(self) -> None:
        entry = self._selected_omnivoice_transcript()
        if entry is None:
            return
        selected = filedialog.asksaveasfilename(
            title="Xuất transcript",
            defaultextension=".srt",
            filetypes=[("SubRip", "*.srt"), ("Văn bản", "*.txt")],
        )
        if not selected:
            return
        destination = Path(selected)
        content = (
            entry.text
            if destination.suffix.casefold() == ".txt"
            else entry.translated_srt or entry.source_srt
        )
        destination.write_text(content, encoding="utf-8")

    def _copy_omnivoice_transcript(self) -> None:
        entry = self._selected_omnivoice_transcript()
        if entry is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(entry.text)
        self.status.set("Đã sao chép transcript")

    def _export_all_omnivoice_transcripts(self) -> None:
        selected = filedialog.askdirectory(title="Chọn thư mục xuất transcript")
        if not selected:
            return
        output_dir = Path(selected)
        exported = 0
        for index, entry in enumerate(self.omnivoice_transcript_store.list(), start=1):
            source_name = Path(entry.source_path).stem or f"transcript-{index:03d}"
            base = output_dir / f"{index:03d}-{source_name}"
            (base.with_suffix(".txt")).write_text(entry.text, encoding="utf-8")
            if entry.source_srt:
                (base.with_name(base.name + "-source").with_suffix(".srt")).write_text(
                    entry.source_srt, encoding="utf-8"
                )
            if entry.translated_srt:
                (base.with_name(base.name + "-translated").with_suffix(".srt")).write_text(
                    entry.translated_srt, encoding="utf-8"
                )
            exported += 1
        messagebox.showinfo("Xuất transcript", f"Đã xuất {exported} transcript.")

    def _delete_omnivoice_transcript(self) -> None:
        entry = self._selected_omnivoice_transcript()
        if entry is None:
            return
        self.omnivoice_transcript_store.delete(entry.entry_id)
        self._refresh_omnivoice_transcripts()

    def _clear_omnivoice_transcripts(self) -> None:
        if not messagebox.askyesno("Xóa lịch sử", "Xóa toàn bộ lịch sử transcript?"):
            return
        self.omnivoice_transcript_store.clear()
        self._refresh_omnivoice_transcripts()

    def _open_omnivoice_workspace_result(self) -> bool:
        if self.omnivoice_workspace_result is None:
            return False
        os.startfile(self.omnivoice_workspace_result.project_dir)
        return True

    def _play_omnivoice_workspace_result(self) -> bool:
        if self.omnivoice_workspace_result is None:
            return False
        os.startfile(self.omnivoice_workspace_result.preview_path)
        return True


__all__ = ["OmniVoiceWorkspaceGuiMixin"]
