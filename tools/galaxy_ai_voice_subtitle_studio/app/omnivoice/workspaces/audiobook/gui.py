from __future__ import annotations

import re
import tkinter as tk
from dataclasses import asdict, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..longform import PAUSE_SPAN, SPEECH_SPAN, LongformPlan, LongformSpan
from ..renderer import find_resumable_workspace_jobs
from .planner import AudiobookOverrides, build_audiobook_plan


class AudiobookWorkspaceGuiMixin:
    def _init_audiobook_workspace_state(self) -> None:
        self.omnivoice_audiobook_cover = tk.StringVar(value="")
        self.omnivoice_audiobook_chapter = tk.StringVar(value="")
        self.omnivoice_audiobook_chapter_speed = tk.DoubleVar(value=1.0)
        self.omnivoice_audiobook_chapter_pause = tk.IntVar(value=500)
        self.omnivoice_audiobook_stats = tk.StringVar(value="Chưa phân tích sách")
        self.omnivoice_audiobook_resume_choice = tk.StringVar(value="")
        self.omnivoice_audiobook_overrides: dict[str, AudiobookOverrides] = {}
        self._omnivoice_audiobook_resume_by_label: dict[str, Path] = {}

    def _build_audiobook_workspace_editor(self, notebook: ttk.Notebook) -> None:
        self._build_editable_longform_tab(notebook, "audiobook")
        page = ttk.Frame(notebook, padding=9)
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(1, weight=1)
        notebook.add(page, text="Thiết lập sách")

        ttk.Label(page, text="Ảnh bìa", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        cover_row = ttk.Frame(page)
        cover_row.grid(row=0, column=1, sticky="ew")
        cover_row.columnconfigure(0, weight=1)
        cover = ttk.Entry(cover_row, textvariable=self.omnivoice_audiobook_cover)
        cover.grid(row=0, column=0, sticky="ew")
        browse = ttk.Button(cover_row, text="Chọn", command=self._browse_audiobook_cover)
        browse.grid(row=0, column=1, padx=(6, 0))
        self.omnivoice_mutable_widgets.extend((cover, browse))

        lexicon_panel = ttk.Frame(page, style="Panel.TFrame", padding=9)
        lexicon_panel.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(8, 0))
        lexicon_panel.columnconfigure(0, weight=1)
        lexicon_panel.rowconfigure(1, weight=1)
        ttk.Label(lexicon_panel, text="Từ điển phát âm", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.omnivoice_audiobook_lexicon_text = tk.Text(
            lexicon_panel, wrap="none", font=("Consolas", 9), height=12, width=28
        )
        self.omnivoice_audiobook_lexicon_text.grid(row=1, column=0, sticky="nsew", pady=6)
        ttk.Label(
            lexicon_panel,
            text="Mỗi dòng: từ gốc = cách đọc",
            style="Panel.TLabel",
        ).grid(row=2, column=0, sticky="w")
        self.omnivoice_mutable_widgets.append(self.omnivoice_audiobook_lexicon_text)

        chapter_panel = ttk.Frame(page, style="Panel.TFrame", padding=9)
        chapter_panel.grid(row=1, column=1, sticky="nsew", pady=(8, 0))
        chapter_panel.columnconfigure(0, weight=1)
        chapter_panel.rowconfigure(1, weight=1)
        ttk.Label(chapter_panel, text="Chương", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        tree = ttk.Treeview(
            chapter_panel,
            columns=("chapter", "speed", "pause"),
            show="headings",
            height=8,
        )
        for column, label, width in (
            ("chapter", "Tên chương", 160),
            ("speed", "Tốc độ", 60),
            ("pause", "Nghỉ ms", 65),
        ):
            tree.heading(column, text=label)
            tree.column(column, width=width, stretch=column == "chapter")
        tree.grid(row=1, column=0, sticky="nsew", pady=6)
        tree.bind("<<TreeviewSelect>>", lambda _event: self._load_audiobook_chapter())
        self.omnivoice_audiobook_chapter_tree = tree

        overrides = ttk.Frame(chapter_panel, style="Surface.TFrame")
        overrides.grid(row=2, column=0, sticky="ew")
        overrides.columnconfigure((1, 3), weight=1)
        ttk.Label(overrides, text="Tốc độ").grid(row=0, column=0)
        speed = ttk.Spinbox(
            overrides,
            textvariable=self.omnivoice_audiobook_chapter_speed,
            from_=0.5,
            to=1.5,
            increment=0.05,
            width=8,
        )
        speed.grid(row=0, column=1, sticky="ew", padx=(4, 8))
        ttk.Label(overrides, text="Nghỉ cuối chương").grid(row=0, column=2)
        pause = ttk.Spinbox(
            overrides,
            textvariable=self.omnivoice_audiobook_chapter_pause,
            from_=0,
            to=10000,
            increment=100,
            width=8,
        )
        pause.grid(row=0, column=3, sticky="ew", padx=(4, 0))
        apply_button = ttk.Button(
            overrides,
            text="Áp dụng cho chương",
            command=self._apply_audiobook_chapter,
        )
        apply_button.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        preview_chapter = ttk.Button(
            overrides,
            text="Nghe thử chương",
            command=self._preview_audiobook_chapter,
        )
        preview_chapter.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.omnivoice_mutable_widgets.extend((speed, pause, apply_button, preview_chapter))

        bottom = ttk.Frame(page)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.omnivoice_audiobook_stats).grid(
            row=0, column=0, sticky="w"
        )
        analyze = ttk.Button(bottom, text="Phân tích", command=self._analyze_audiobook)
        analyze.grid(row=0, column=1, padx=(6, 0))
        resume = ttk.Combobox(
            bottom,
            textvariable=self.omnivoice_audiobook_resume_choice,
            state="readonly",
            width=32,
        )
        resume.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        resume_button = ttk.Button(bottom, text="Chạy tiếp", command=self._resume_audiobook)
        resume_button.grid(row=1, column=1, padx=(6, 0), pady=(7, 0))
        self.omnivoice_audiobook_resume_combo = resume
        self.omnivoice_mutable_widgets.extend((analyze, resume, resume_button))
        self._refresh_audiobook_resume_jobs()

    def _browse_audiobook_cover(self) -> None:
        selected = filedialog.askopenfilename(
            title="Chọn ảnh bìa",
            filetypes=[("Ảnh", "*.jpg *.jpeg *.png *.webp"), ("Tất cả file", "*.*")],
        )
        if selected:
            self.omnivoice_audiobook_cover.set(selected)

    def _audiobook_lexicon(self) -> dict[str, str]:
        if not hasattr(self, "omnivoice_audiobook_lexicon_text"):
            return {}
        result: dict[str, str] = {}
        for raw_line in self.omnivoice_audiobook_lexicon_text.get("1.0", "end").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            source, replacement = line.split("=", 1)
            if source.strip() and replacement.strip():
                result[source.strip()] = replacement.strip()
        return result

    def _prepare_audiobook_plan(self, plan: LongformPlan) -> LongformPlan:
        lexicon = self._audiobook_lexicon()
        spans: list[LongformSpan] = []
        previous_chapter = ""
        for span in plan.spans:
            if previous_chapter and span.chapter != previous_chapter:
                self._append_audiobook_chapter_pause(spans, previous_chapter)
            override = self.omnivoice_audiobook_overrides.get(
                span.chapter, AudiobookOverrides()
            )
            if span.kind == SPEECH_SPAN:
                text = span.text
                for source, replacement in sorted(
                    lexicon.items(), key=lambda item: len(item[0]), reverse=True
                ):
                    text = re.sub(re.escape(source), replacement, text, flags=re.IGNORECASE)
                span = replace(
                    span,
                    text=text,
                    speed=max(0.5, min(1.5, span.speed * override.speed)),
                )
            spans.append(span)
            previous_chapter = span.chapter
        if previous_chapter:
            self._append_audiobook_chapter_pause(spans, previous_chapter)
        return LongformPlan(tuple(spans), plan.chapters)

    def _append_audiobook_chapter_pause(
        self, spans: list[LongformSpan], chapter: str
    ) -> None:
        pause_ms = self.omnivoice_audiobook_overrides.get(
            chapter, AudiobookOverrides()
        ).pause_after_ms
        if pause_ms > 0:
            spans.append(
                LongformSpan(kind=PAUSE_SPAN, pause_ms=pause_ms, chapter=chapter)
            )

    def _analyze_audiobook(self) -> None:
        source = self.omnivoice_audiobook_text.get("1.0", "end")
        try:
            plan = build_audiobook_plan(
                source,
                cast=self.omnivoice_audiobook_cast,
                lexicon=self._audiobook_lexicon(),
                overrides=self.omnivoice_audiobook_overrides,
            )
            self._load_workspace_document("audiobook", force=True)
        except ValueError as error:
            messagebox.showerror("Không phân tích được sách", str(error))
            return
        stats = plan.stats
        minutes = max(1, round(stats.estimated_seconds / 60))
        self.omnivoice_audiobook_stats.set(
            f"{stats.chapter_count} chương | {stats.span_count} đoạn | "
            f"{stats.word_count} từ | khoảng {minutes} phút"
        )
        self._refresh_audiobook_chapters()
        issues = (*plan.errors, *plan.warnings)
        if issues:
            messagebox.showwarning(
                "Kiểm tra audiobook",
                "\n".join(f"- {issue.message}" for issue in issues[:20]),
            )

    def _refresh_audiobook_chapters(self) -> None:
        tree = getattr(self, "omnivoice_audiobook_chapter_tree", None)
        document = self.omnivoice_workspace_documents.get("audiobook")
        if tree is None or document is None:
            return
        tree.delete(*tree.get_children())
        for index, chapter in enumerate(document.chapters):
            override = self.omnivoice_audiobook_overrides.get(chapter, AudiobookOverrides())
            tree.insert(
                "",
                "end",
                iid=f"chapter-{index}",
                values=(chapter, f"{override.speed:.2f}", override.pause_after_ms),
            )

    def _load_audiobook_chapter(self) -> None:
        selection = self.omnivoice_audiobook_chapter_tree.selection()
        if not selection:
            return
        chapter = str(self.omnivoice_audiobook_chapter_tree.item(selection[0], "values")[0])
        override = self.omnivoice_audiobook_overrides.get(chapter, AudiobookOverrides())
        self.omnivoice_audiobook_chapter.set(chapter)
        self.omnivoice_audiobook_chapter_speed.set(override.speed)
        self.omnivoice_audiobook_chapter_pause.set(override.pause_after_ms)

    def _apply_audiobook_chapter(self) -> None:
        chapter = self.omnivoice_audiobook_chapter.get().strip()
        if not chapter:
            return
        try:
            override = AudiobookOverrides(
                speed=max(0.5, min(1.5, float(self.omnivoice_audiobook_chapter_speed.get()))),
                pause_after_ms=max(0, min(10_000, int(self.omnivoice_audiobook_chapter_pause.get()))),
            )
        except (tk.TclError, TypeError, ValueError) as error:
            messagebox.showerror("Thiết lập chương chưa hợp lệ", str(error))
            return
        self.omnivoice_audiobook_overrides[chapter] = override
        self._refresh_audiobook_chapters()

    def _preview_audiobook_chapter(self) -> None:
        chapter = self.omnivoice_audiobook_chapter.get().strip()
        document = self.omnivoice_workspace_documents.get("audiobook")
        if not chapter or document is None:
            return
        items = [item for item in document.items if item.chapter == chapter]
        if not items:
            return
        plan = self._prepare_audiobook_plan(
            type(document)(items=items, chapters=[chapter]).to_plan()
        )
        self._start_audiobook_chapter_preview(chapter, plan)

    def _get_audiobook_project_payload(self) -> dict[str, object]:
        return {
            "title": self.omnivoice_audiobook_title.get(),
            "author": self.omnivoice_audiobook_author.get(),
            "cover": self.omnivoice_audiobook_cover.get(),
            "lexicon": self._audiobook_lexicon(),
            "overrides": {
                chapter: asdict(value)
                for chapter, value in self.omnivoice_audiobook_overrides.items()
            },
        }

    def _restore_audiobook_project_payload(self, payload: dict[str, object]) -> None:
        self.omnivoice_audiobook_title.set(str(payload.get("title") or ""))
        self.omnivoice_audiobook_author.set(str(payload.get("author") or ""))
        self.omnivoice_audiobook_cover.set(str(payload.get("cover") or ""))
        lexicon = payload.get("lexicon")
        if isinstance(lexicon, dict):
            self.omnivoice_audiobook_lexicon_text.delete("1.0", "end")
            self.omnivoice_audiobook_lexicon_text.insert(
                "1.0", "\n".join(f"{key} = {value}" for key, value in lexicon.items())
            )
        raw_overrides = payload.get("overrides")
        self.omnivoice_audiobook_overrides = (
            {
                str(chapter): AudiobookOverrides(**value)
                for chapter, value in raw_overrides.items()
                if isinstance(value, dict)
            }
            if isinstance(raw_overrides, dict)
            else {}
        )
        self._refresh_audiobook_chapters()

    def _refresh_audiobook_resume_jobs(self) -> None:
        jobs = find_resumable_workspace_jobs(Path(self.omnivoice_output_dir.get()))
        self._omnivoice_audiobook_resume_by_label = {
            f"{job.project_name} ({job.completed_spans}/{job.total_spans})": job.project_dir
            for job in jobs
        }
        if hasattr(self, "omnivoice_audiobook_resume_combo"):
            self.omnivoice_audiobook_resume_combo.configure(
                values=tuple(self._omnivoice_audiobook_resume_by_label)
            )

    def _resume_audiobook(self) -> None:
        self._refresh_audiobook_resume_jobs()
        project_dir = self._omnivoice_audiobook_resume_by_label.get(
            self.omnivoice_audiobook_resume_choice.get()
        )
        if project_dir is None:
            messagebox.showinfo("Chạy tiếp audiobook", "Không có job dở được chọn.")
            return
        self._start_omnivoice_workspace("audiobook", resume_project_dir=project_dir)
