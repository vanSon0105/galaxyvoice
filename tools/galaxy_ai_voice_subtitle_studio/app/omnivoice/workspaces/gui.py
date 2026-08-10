from __future__ import annotations

import os
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ...voice.srt import parse_srt
from ...voice.transcription import VideoSubtitleDraft
from ..models import AUTO_MODE, CLONE_MODE, DESIGN_MODE, OmniVoiceGenerationOptions
from ..runtime import inspect_runtime
from .gallery import VoiceArchetype, list_voice_archetypes, voice_archetype_categories
from .imports import load_audiobook_source
from .longform import (
    LongformPlan,
    parse_audiobook_script,
    parse_story_script,
    plan_dubbing_cues,
)
from .renderer import LongformWorkspaceResult, render_longform_plan
from .transcripts import TranscriptEntry, TranscriptStore


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


class OmniVoiceWorkspaceGuiMixin:
    def _init_omnivoice_workspace_state(self) -> None:
        self.omnivoice_workspace_result: LongformWorkspaceResult | None = None
        self.omnivoice_last_dub_result: LongformWorkspaceResult | None = None
        self.omnivoice_story_project_name = tk.StringVar(value="omnivoice-story")
        self.omnivoice_audiobook_project_name = tk.StringVar(value="omnivoice-audiobook")
        self.omnivoice_audiobook_title = tk.StringVar(value="")
        self.omnivoice_audiobook_author = tk.StringVar(value="")
        self.omnivoice_audiobook_export_m4b = tk.BooleanVar(value=True)
        self.omnivoice_story_cast_choice = tk.StringVar(value="")
        self.omnivoice_audiobook_cast_choice = tk.StringVar(value="")
        self.omnivoice_story_cast: dict[str, str] = {}
        self.omnivoice_audiobook_cast: dict[str, str] = {}
        self.omnivoice_gallery_search = tk.StringVar(value="")
        self.omnivoice_gallery_category = tk.StringVar(value="Tất cả")
        self.omnivoice_transcript_search = tk.StringVar(value="")
        self.omnivoice_transcript_store = TranscriptStore(
            self.config_path.with_name("transcriptions.json")
        )

    def _build_omnivoice_workspace_tabs(self, notebook: ttk.Notebook) -> None:
        self._build_omnivoice_longform_workspace(notebook, "stories")
        self._build_omnivoice_longform_workspace(notebook, "audiobook")
        self._build_omnivoice_gallery_workspace(notebook)
        self._build_omnivoice_transcripts_workspace(notebook)

    def _build_omnivoice_longform_workspace(
        self,
        notebook: ttk.Notebook,
        kind: str,
    ) -> None:
        is_story = kind == "stories"
        title = "Stories" if is_story else "Audiobook"
        page = ttk.Frame(notebook, padding=12)
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2, minsize=330)
        page.rowconfigure(0, weight=1)
        notebook.add(page, text=title)
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
        if not is_story:
            tool_specs.insert(0, ("Nhập sách", self._import_omnivoice_audiobook))
        for column, (label, command) in enumerate(tool_specs):
            button = ttk.Button(tools, text=label, command=command)
            button.grid(row=0, column=column, padx=(0, 5))
            self.omnivoice_mutable_widgets.append(button)

        text_frame = ttk.Frame(editor, style="Surface.TFrame")
        text_frame.grid(row=1, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        text_widget = tk.Text(
            text_frame,
            wrap="word",
            font=("Segoe UI", 10),
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

        controls = ttk.Frame(page, style="Panel.TFrame", padding=12)
        controls.grid(row=0, column=1, sticky="nsew")
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
        tree.column("character", width=115, stretch=True)
        tree.column("profile", width=150, stretch=True)
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
        notebook.add(page, text="Voice Gallery")
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
        self.omnivoice_mutable_widgets.extend((search, category))
        search.bind("<KeyRelease>", lambda _event: self._refresh_omnivoice_gallery())
        category.bind("<<ComboboxSelected>>", lambda _event: self._refresh_omnivoice_gallery())

        tree_frame = ttk.Frame(presets, style="Panel.TFrame", padding=7)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 9))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.omnivoice_gallery_tree = ttk.Treeview(
            tree_frame,
            columns=("name", "use_case", "language"),
            show="headings",
            selectmode="browse",
        )
        for column, label, width in (
            ("name", "Giọng", 190),
            ("use_case", "Mục đích", 110),
            ("language", "Ngôn ngữ", 85),
        ):
            self.omnivoice_gallery_tree.heading(column, text=label)
            self.omnivoice_gallery_tree.column(column, width=width, stretch=True)
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
            details, wrap="word", height=12, font=("Segoe UI", 9), state="disabled"
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
            self.omnivoice_transcript_tree.column(column, width=width, stretch=True)
        self.omnivoice_transcript_tree.grid(row=0, column=0, sticky="nsew")
        self.omnivoice_transcript_tree.bind(
            "<<TreeviewSelect>>", lambda _event: self._show_omnivoice_transcript()
        )

        details = ttk.Frame(page, style="Panel.TFrame", padding=9)
        details.grid(row=1, column=1, sticky="nsew")
        details.columnconfigure(0, weight=1)
        details.rowconfigure(0, weight=1)
        self.omnivoice_transcript_details = tk.Text(
            details, wrap="word", font=("Segoe UI", 9), state="disabled"
        )
        self.omnivoice_transcript_details.grid(row=0, column=0, sticky="nsew")
        actions = ttk.Frame(details, style="Surface.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        actions.columnconfigure((0, 1), weight=1)
        for index, (label, command) in enumerate(
            (
                ("Đưa sang Dubbing", self._use_transcript_in_dubbing),
                ("Xuất SRT", self._export_omnivoice_transcript),
                ("Xóa", self._delete_omnivoice_transcript),
                ("Xóa lịch sử", self._clear_omnivoice_transcripts),
            )
        ):
            button = ttk.Button(actions, text=label, command=command)
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=3, pady=3)
            self.omnivoice_mutable_widgets.append(button)
        self._refresh_omnivoice_transcripts()

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

    def _workspace_plan(self, kind: str) -> LongformPlan:
        source = getattr(self, f"omnivoice_{kind}_text").get("1.0", "end")
        return parse_story_script(source) if kind == "stories" else parse_audiobook_script(source)

    def _scan_workspace_cast(self, kind: str) -> None:
        try:
            plan = self._workspace_plan(kind)
        except ValueError as error:
            messagebox.showerror("Nội dung chưa hợp lệ", str(error))
            return
        tree: ttk.Treeview = getattr(self, f"omnivoice_{kind}_cast_tree")
        cast: dict[str, str] = getattr(self, f"omnivoice_{kind}_cast")
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
        cast: dict[str, str] = getattr(self, f"omnivoice_{kind}_cast")
        if profile is None:
            cast.pop(character, None)
        else:
            cast[character] = profile.profile_id
        self._scan_workspace_cast(kind)

    def _start_omnivoice_workspace(self, kind: str) -> None:
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
        cast = dict(getattr(self, f"omnivoice_{kind}_cast"))
        self._start_omnivoice_thread(
            f"omnivoice_{kind}",
            self._run_omnivoice_workspace,
            (kind, options, plan, cast),
            f"omnivoice-{kind}",
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
            ("dubbing", options, plan, {}),
            "omnivoice-dubbing",
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
                title=self.omnivoice_audiobook_title.get() if kind == "audiobook" else "",
                author=self.omnivoice_audiobook_author.get() if kind == "audiobook" else "",
                progress=lambda message: self.events.put(("omnivoice_progress", message)),
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
        for warning in result.warnings:
            self._append_omnivoice_log(f"Cảnh báo: {warning}")

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
        self.omnivoice_gallery_tree.delete(*self.omnivoice_gallery_tree.get_children())
        for item in items:
            self.omnivoice_gallery_tree.insert(
                "", "end", iid=item.archetype_id, values=(item.name, item.use_case, item.language)
            )
        if items:
            self.omnivoice_gallery_tree.selection_set(items[0].archetype_id)
            self._show_omnivoice_archetype()

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
