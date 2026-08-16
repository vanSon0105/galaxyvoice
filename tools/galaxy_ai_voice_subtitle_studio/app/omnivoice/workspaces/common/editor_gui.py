from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox, ttk

from ..editable import EditableLongformDocument, EditableLongformItem
from ..longform import LongformPlan


LONGFORM_WORKSPACE = "longform"


class EditableLongformGuiMixin:
    def _init_editable_longform_state(self) -> None:
        self.omnivoice_workspace_documents: dict[str, EditableLongformDocument | None] = {
            "stories": None,
            "audiobook": None,
        }
        self.omnivoice_workspace_source_snapshot = {"stories": "", "audiobook": ""}
        self.omnivoice_workspace_project_ids = {"stories": "", "audiobook": ""}
        self.omnivoice_workspace_editor_vars: dict[str, dict[str, tk.Variable]] = {}
        for kind in ("stories", "audiobook"):
            self.omnivoice_workspace_editor_vars[kind] = {
                "chapter": tk.StringVar(value=""),
                "speaker": tk.StringVar(value=""),
                "profile": tk.StringVar(value=""),
                "speed": tk.DoubleVar(value=1.0),
                "volume": tk.DoubleVar(value=1.0),
                "pause": tk.IntVar(value=0),
                "status": tk.StringVar(value="Chưa lập kế hoạch"),
            }

    def _build_editable_longform_tab(
        self,
        notebook: ttk.Notebook,
        kind: str,
    ) -> ttk.Frame:
        page = ttk.Frame(notebook, padding=7)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        notebook.add(page, text="Kế hoạch")

        toolbar = ttk.Frame(page)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        specs = (
            ("Nạp từ script", lambda: self._load_workspace_document(kind, force=True)),
            ("Kiểm tra", lambda: self._validate_workspace_document(kind)),
            ("Lưu project", lambda: self._save_workspace_project(kind)),
            ("Mở project", lambda: self._open_workspace_project(kind)),
        )
        for column, (label, command) in enumerate(specs):
            button = ttk.Button(toolbar, text=label, command=command)
            button.grid(row=0, column=column, padx=(0, 6))
            self.omnivoice_mutable_widgets.append(button)

        table = ttk.Frame(page, style="Panel.TFrame", padding=6)
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            table,
            columns=("chapter", "speaker", "text", "speed", "pause"),
            show="headings",
            selectmode="browse",
        )
        for column, label, width in (
            ("chapter", "Chương", 120),
            ("speaker", "Vai", 100),
            ("text", "Nội dung", 330),
            ("speed", "Tốc độ", 65),
            ("pause", "Nghỉ", 65),
        ):
            tree.heading(column, text=label)
            tree.column(column, width=self._px(width), stretch=column == "text")
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)
        tree.bind(
            "<<TreeviewSelect>>",
            lambda _event: self._load_selected_workspace_item(kind),
        )
        editor_page = ttk.Frame(notebook, padding=7)
        editor_page.columnconfigure(0, weight=1)
        editor_page.rowconfigure(0, weight=1)
        notebook.add(editor_page, text="Chỉnh đoạn")
        tree.bind(
            "<Double-1>",
            lambda _event: notebook.select(editor_page),
        )
        setattr(self, f"omnivoice_{kind}_item_tree", tree)
        setattr(self, f"omnivoice_{kind}_item_editor_tab", editor_page)

        inspector = ttk.Frame(editor_page, style="Panel.TFrame", padding=9)
        inspector.grid(row=0, column=0, sticky="nsew")
        inspector.columnconfigure(1, weight=1)
        inspector.rowconfigure(4, weight=1)
        variables = self.omnivoice_workspace_editor_vars[kind]
        row = 0
        for label, key in (("Chương", "chapter"), ("Vai/người đọc", "speaker")):
            ttk.Label(inspector, text=label, style="Panel.TLabel").grid(
                row=row, column=0, sticky="w", pady=3
            )
            entry = ttk.Entry(inspector, textvariable=variables[key])
            entry.grid(row=row, column=1, sticky="ew", padx=(7, 0), pady=3)
            self.omnivoice_mutable_widgets.append(entry)
            row += 1
        ttk.Label(inspector, text="Profile", style="Panel.TLabel").grid(
            row=row, column=0, sticky="w", pady=3
        )
        profile = ttk.Combobox(
            inspector,
            textvariable=variables["profile"],
            state="readonly",
        )
        profile.grid(row=row, column=1, sticky="ew", padx=(7, 0), pady=3)
        self.omnivoice_profile_combos.append(profile)
        self.omnivoice_mutable_widgets.append(profile)
        row += 1
        ttk.Label(inspector, text="Nội dung", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(5, 3)
        )
        row += 1
        text = tk.Text(inspector, height=8, wrap="word", undo=True, font="TkTextFont")
        text.grid(row=row, column=0, columnspan=2, sticky="nsew")
        setattr(self, f"omnivoice_{kind}_item_text", text)
        self.omnivoice_mutable_widgets.append(text)
        row += 1

        numeric = ttk.Frame(inspector, style="Surface.TFrame")
        numeric.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        numeric.columnconfigure((1, 3, 5), weight=1)
        for offset, (label, key, start, end, step) in enumerate(
            (
                ("Tốc độ", "speed", 0.5, 1.5, 0.05),
                ("Âm lượng", "volume", 0.0, 2.0, 0.1),
                ("Nghỉ ms", "pause", 0, 10000, 50),
            )
        ):
            ttk.Label(numeric, text=label, style="Panel.TLabel").grid(
                row=0, column=offset * 2, sticky="w", padx=(0 if offset == 0 else 7, 3)
            )
            spin = ttk.Spinbox(
                numeric,
                textvariable=variables[key],
                from_=start,
                to=end,
                increment=step,
                width=7,
            )
            spin.grid(row=0, column=offset * 2 + 1, sticky="ew")
            self.omnivoice_mutable_widgets.append(spin)
        row += 1

        actions = ttk.Frame(inspector, style="Surface.TFrame")
        actions.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        actions.columnconfigure((0, 1, 2), weight=1)
        action_specs = (
            ("Áp dụng", lambda: self._apply_workspace_item(kind)),
            ("Nghe thử", lambda: self._preview_workspace_item(kind)),
            ("Tách", lambda: self._split_workspace_item(kind)),
            ("Lên", lambda: self._move_workspace_item(kind, -1)),
            ("Xuống", lambda: self._move_workspace_item(kind, 1)),
            ("Ghép câu sau", lambda: self._merge_workspace_item(kind)),
            ("Thêm", lambda: self._add_workspace_item(kind)),
            ("Xóa", lambda: self._delete_workspace_item(kind)),
        )
        for index, (label, command) in enumerate(action_specs):
            button = ttk.Button(actions, text=label, command=command)
            button.grid(row=index // 3, column=index % 3, sticky="ew", padx=2, pady=2)
            self.omnivoice_mutable_widgets.append(button)
        row += (len(action_specs) + 2) // 3
        ttk.Label(
            inspector,
            textvariable=variables["status"],
            style="Panel.TLabel",
            wraplength=self._px(300),
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(7, 0))
        return page

    def _load_workspace_document(self, kind: str, *, force: bool = False) -> LongformPlan:
        source = getattr(self, f"omnivoice_{kind}_text").get("1.0", "end").strip()
        current = self.omnivoice_workspace_documents.get(kind)
        if not force and current is not None:
            if self.omnivoice_workspace_source_snapshot.get(kind) == source:
                return self._prepared_workspace_plan(kind, current)
        document = (
            EditableLongformDocument.from_story(source)
            if kind == "stories"
            else EditableLongformDocument.from_audiobook(source)
        )
        self.omnivoice_workspace_documents[kind] = document
        self.omnivoice_workspace_source_snapshot[kind] = source
        self._refresh_workspace_item_tree(kind)
        return self._prepared_workspace_plan(kind, document)

    def _prepared_workspace_plan(
        self,
        kind: str,
        document: EditableLongformDocument,
    ) -> LongformPlan:
        plan = document.to_plan()
        prepare = getattr(self, f"_prepare_{kind}_plan", None)
        return prepare(plan) if callable(prepare) else plan

    def _refresh_workspace_item_tree(self, kind: str, selected_id: str = "") -> None:
        tree = getattr(self, f"omnivoice_{kind}_item_tree", None)
        document = self.omnivoice_workspace_documents.get(kind)
        if tree is None or document is None:
            return
        tree.delete(*tree.get_children())
        for item in document.items:
            tree.insert(
                "",
                "end",
                iid=item.item_id,
                values=(
                    item.chapter,
                    item.speaker or "Mặc định",
                    item.text.replace("\n", " "),
                    f"{item.speed:.2f}",
                    item.pause_after_ms,
                ),
            )
        if selected_id and tree.exists(selected_id):
            tree.selection_set(selected_id)
            tree.focus(selected_id)
            tree.see(selected_id)
        variables = self.omnivoice_workspace_editor_vars[kind]
        word_count = sum(len(item.text.split()) for item in document.items)
        variables["status"].set(
            f"{len(document.chapters)} chương | {len(document.items)} đoạn | {word_count} từ"
        )

    def _selected_workspace_item(self, kind: str) -> EditableLongformItem | None:
        tree = getattr(self, f"omnivoice_{kind}_item_tree")
        selection = tree.selection()
        document = self.omnivoice_workspace_documents.get(kind)
        return document.get(selection[0]) if selection and document is not None else None

    def _load_selected_workspace_item(self, kind: str) -> None:
        item = self._selected_workspace_item(kind)
        if item is None:
            return
        variables = self.omnivoice_workspace_editor_vars[kind]
        variables["chapter"].set(item.chapter)
        variables["speaker"].set(item.speaker)
        variables["speed"].set(item.speed)
        variables["volume"].set(item.volume)
        variables["pause"].set(item.pause_after_ms)
        label = next(
            (
                name
                for name, profile in self._omnivoice_profile_by_label.items()
                if profile.profile_id == item.profile_id
            ),
            "",
        )
        variables["profile"].set(label)
        text = getattr(self, f"omnivoice_{kind}_item_text")
        text.delete("1.0", "end")
        text.insert("1.0", item.text)

    def _apply_workspace_item(self, kind: str) -> EditableLongformItem | None:
        item = self._selected_workspace_item(kind)
        document = self.omnivoice_workspace_documents.get(kind)
        if item is None or document is None:
            return None
        variables = self.omnivoice_workspace_editor_vars[kind]
        profile = self._omnivoice_profile_by_label.get(str(variables["profile"].get()))
        try:
            updated = document.update(
                item.item_id,
                chapter=str(variables["chapter"].get()).strip() or "Content",
                speaker=str(variables["speaker"].get()).strip(),
                profile_id=profile.profile_id if profile else "",
                text=getattr(self, f"omnivoice_{kind}_item_text").get("1.0", "end").strip(),
                speed=max(0.5, min(1.5, float(variables["speed"].get()))),
                volume=max(0.0, min(2.0, float(variables["volume"].get()))),
                pause_after_ms=max(0, min(10_000, int(variables["pause"].get()))),
                preview_path="",
            )
        except (tk.TclError, TypeError, ValueError) as error:
            messagebox.showerror("Thiết lập đoạn chưa hợp lệ", str(error))
            return None
        self._refresh_workspace_item_tree(kind, updated.item_id)
        return updated

    def _move_workspace_item(self, kind: str, delta: int) -> None:
        item = self._apply_workspace_item(kind)
        document = self.omnivoice_workspace_documents.get(kind)
        if item is not None and document is not None:
            document.move(item.item_id, delta)
            self._refresh_workspace_item_tree(kind, item.item_id)

    def _split_workspace_item(self, kind: str) -> None:
        item = self._apply_workspace_item(kind)
        document = self.omnivoice_workspace_documents.get(kind)
        if item is None or document is None:
            return
        try:
            _left, right = document.split(item.item_id)
        except ValueError as error:
            messagebox.showerror("Không tách được đoạn", str(error))
            return
        self._refresh_workspace_item_tree(kind, right)

    def _merge_workspace_item(self, kind: str) -> None:
        item = self._apply_workspace_item(kind)
        document = self.omnivoice_workspace_documents.get(kind)
        if item is None or document is None:
            return
        index = document.items.index(item)
        if index >= len(document.items) - 1:
            return
        merged_id = document.merge(item.item_id, document.items[index + 1].item_id)
        self._refresh_workspace_item_tree(kind, merged_id)

    def _add_workspace_item(self, kind: str) -> None:
        document = self.omnivoice_workspace_documents.get(kind)
        if document is None:
            try:
                self._load_workspace_document(kind)
            except ValueError:
                document = EditableLongformDocument(items=[], chapters=["Content"])
                self.omnivoice_workspace_documents[kind] = document
        document = self.omnivoice_workspace_documents[kind]
        selected = self._selected_workspace_item(kind)
        item = document.add(after_id=selected.item_id if selected else "")
        self._refresh_workspace_item_tree(kind, item.item_id)

    def _delete_workspace_item(self, kind: str) -> None:
        item = self._selected_workspace_item(kind)
        document = self.omnivoice_workspace_documents.get(kind)
        if item is not None and document is not None:
            document.delete(item.item_id)
            self._refresh_workspace_item_tree(kind)

    def _preview_workspace_item(self, kind: str) -> None:
        item = self._apply_workspace_item(kind)
        if item is not None and item.text.strip():
            self._start_longform_item_preview(kind, item)

    def _validate_workspace_document(self, kind: str) -> None:
        try:
            plan = self._load_workspace_document(kind)
        except ValueError as error:
            messagebox.showerror("Project chưa hợp lệ", str(error))
            return
        document = self.omnivoice_workspace_documents[kind]
        assert document is not None
        warnings: list[str] = []
        for item in document.items:
            if not item.text.strip():
                warnings.append(f"Đoạn {item.item_id} đang trống.")
            if len(item.text) > 500:
                warnings.append(f"Đoạn {item.item_id} dài {len(item.text)} ký tự.")
            if item.speaker and not item.profile_id:
                cast = self._workspace_cast(kind)
                if not cast.get(item.speaker):
                    warnings.append(f"Vai '{item.speaker}' chưa được gán profile.")
        message = (
            "Project hợp lệ.\n"
            f"{len(plan.chapters)} chương, {len(document.items)} đoạn."
        )
        if warnings:
            message += "\n\nCảnh báo:\n- " + "\n- ".join(warnings[:15])
            messagebox.showwarning("Kiểm tra project", message)
        else:
            messagebox.showinfo("Kiểm tra project", message)

    def _save_workspace_project(self, kind: str) -> None:
        try:
            self._load_workspace_document(kind)
        except ValueError as error:
            messagebox.showerror("Không lưu được project", str(error))
            return
        project_name = getattr(self, f"omnivoice_{'story' if kind == 'stories' else 'audiobook'}_project_name")
        payload = self._longform_project_payload(kind)
        project_id = next(
            (
                value
                for value in self.omnivoice_workspace_project_ids.values()
                if value
            ),
            "",
        )
        project = self.omnivoice_workspace_repository.save_project(
            workspace=LONGFORM_WORKSPACE,
            name=project_name.get().strip() or kind,
            project_id=project_id,
            payload=payload,
        )
        for workspace_kind in self.omnivoice_workspace_project_ids:
            self.omnivoice_workspace_project_ids[workspace_kind] = project.project_id
        self.omnivoice_workspace_editor_vars[kind]["status"].set(
            f"Đã lưu project: {project.name}"
        )

    def _longform_project_payload(self, active_mode: str) -> dict[str, object]:
        modes: dict[str, dict[str, object]] = {}
        for kind in ("stories", "audiobook"):
            document = self.omnivoice_workspace_documents.get(kind)
            project_name = getattr(
                self,
                f"omnivoice_{'story' if kind == 'stories' else 'audiobook'}_project_name",
            )
            mode_payload: dict[str, object] = {
                "source": getattr(self, f"omnivoice_{kind}_text")
                .get("1.0", "end")
                .strip(),
                "document": document.to_payload() if document is not None else {},
                "cast": dict(self._workspace_cast(kind)),
                "project_name": project_name.get().strip(),
                "export_stems": bool(
                    self.omnivoice_story_export_stems.get()
                    if kind == "stories"
                    else self.omnivoice_audiobook_export_stems.get()
                ),
            }
            extra = getattr(self, f"_get_{kind}_project_payload", None)
            if callable(extra):
                mode_payload.update(extra())
            if kind == "audiobook":
                mode_payload["export_m4b"] = bool(
                    self.omnivoice_audiobook_export_m4b.get()
                )
            modes[kind] = mode_payload
        return {
            "schema_version": 1,
            "active_mode": active_mode,
            "language": self.omnivoice_language.get(),
            "modes": modes,
        }

    def _open_workspace_project(self, kind: str) -> None:
        projects_by_id = {
            item.project_id: item
            for workspace in (LONGFORM_WORKSPACE, "stories", "audiobook")
            for item in self.omnivoice_workspace_repository.list_projects(workspace)
        }
        projects = tuple(
            sorted(projects_by_id.values(), key=lambda item: item.updated_at, reverse=True)
        )
        if not projects:
            messagebox.showinfo("Projects", "Chưa có project đã lưu.")
            return
        chooser = tk.Toplevel(self.root)
        chooser.title("Mở project")
        chooser.geometry("560x320")
        chooser.transient(self.root)
        chooser.grab_set()
        frame = ttk.Frame(chooser, padding=10)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(
            frame,
            columns=("name", "mode", "updated"),
            show="headings",
        )
        tree.heading("name", text="Project")
        tree.heading("mode", text="Chế độ")
        tree.heading("updated", text="Cập nhật")
        tree.column("name", width=self._px(280))
        tree.column("mode", width=self._px(100))
        tree.column("updated", width=self._px(150))
        tree.pack(fill="both", expand=True)
        for project in projects:
            tree.insert(
                "",
                "end",
                iid=project.project_id,
                values=(
                    project.name,
                    {
                        LONGFORM_WORKSPACE: "Hợp nhất",
                        "stories": "Truyện",
                        "audiobook": "Sách nói",
                    }.get(project.workspace, project.workspace),
                    project.updated_at[:19].replace("T", " "),
                ),
            )

        def restore() -> None:
            selection = tree.selection()
            if not selection:
                return
            project = self.omnivoice_workspace_repository.get_project(selection[0])
            if project is not None:
                self._restore_workspace_project(kind, project)
            chooser.destroy()

        ttk.Button(frame, text="Mở", style="Accent.TButton", command=restore).pack(
            fill="x", pady=(8, 0)
        )

    def _restore_workspace_project(self, kind: str, project) -> None:
        if project.workspace == LONGFORM_WORKSPACE:
            self._restore_longform_project(project)
            return
        if project.workspace in {"stories", "audiobook"}:
            kind = project.workspace
        raw_document = project.payload.get("document")
        if not isinstance(raw_document, dict):
            return
        document = EditableLongformDocument.from_payload(raw_document)
        source = str(project.payload.get("source") or "")
        text = getattr(self, f"omnivoice_{kind}_text")
        text.delete("1.0", "end")
        text.insert("1.0", source)
        self.omnivoice_workspace_documents[kind] = document
        self.omnivoice_workspace_source_snapshot[kind] = source
        self.omnivoice_workspace_project_ids[kind] = project.project_id
        project_name = getattr(self, f"omnivoice_{'story' if kind == 'stories' else 'audiobook'}_project_name")
        project_name.set(project.name)
        raw_cast = project.payload.get("cast")
        if isinstance(raw_cast, dict):
            self._set_workspace_cast(
                kind,
                {str(k): str(v) for k, v in raw_cast.items()},
            )
        restore_extra = getattr(self, f"_restore_{kind}_project_payload", None)
        if callable(restore_extra):
            restore_extra(project.payload)
        self._refresh_workspace_item_tree(kind)
        self._select_omnivoice_longform_mode(kind, sync_project=False)

    def _restore_longform_project(self, project) -> None:
        raw_modes = project.payload.get("modes")
        if not isinstance(raw_modes, dict):
            return
        for kind in ("stories", "audiobook"):
            raw_mode = raw_modes.get(kind)
            if not isinstance(raw_mode, dict):
                continue
            source = str(raw_mode.get("source") or "")
            text = getattr(self, f"omnivoice_{kind}_text")
            text.delete("1.0", "end")
            text.insert("1.0", source)

            raw_document = raw_mode.get("document")
            document = (
                EditableLongformDocument.from_payload(raw_document)
                if isinstance(raw_document, dict) and raw_document.get("items") is not None
                else None
            )
            self.omnivoice_workspace_documents[kind] = document
            self.omnivoice_workspace_source_snapshot[kind] = source

            raw_cast = raw_mode.get("cast")
            self._set_workspace_cast(
                kind,
                {str(key): str(value) for key, value in raw_cast.items()}
                if isinstance(raw_cast, dict)
                else {},
            )
            project_name = getattr(
                self,
                f"omnivoice_{'story' if kind == 'stories' else 'audiobook'}_project_name",
            )
            project_name.set(str(raw_mode.get("project_name") or project.name))
            if kind == "stories":
                self.omnivoice_story_export_stems.set(
                    bool(raw_mode.get("export_stems", False))
                )
            else:
                self.omnivoice_audiobook_export_stems.set(
                    bool(raw_mode.get("export_stems", False))
                )
                self.omnivoice_audiobook_export_m4b.set(
                    bool(raw_mode.get("export_m4b", True))
                )
                self._restore_audiobook_project_payload(raw_mode)
            if document is not None:
                self._refresh_workspace_item_tree(kind)
                if source:
                    self._scan_workspace_cast(kind)

        self.omnivoice_language.set(str(project.payload.get("language") or "vi"))
        for kind in self.omnivoice_workspace_project_ids:
            self.omnivoice_workspace_project_ids[kind] = project.project_id
        active_mode = str(project.payload.get("active_mode") or "stories")
        if active_mode not in {"stories", "audiobook"}:
            active_mode = "stories"
        self._select_omnivoice_longform_mode(active_mode, sync_project=False)

    def _mark_workspace_item_preview(
        self,
        kind: str,
        item_id: str,
        preview_path: Path,
    ) -> None:
        document = self.omnivoice_workspace_documents.get(kind)
        if document is not None and document.get(item_id) is not None:
            document.update(item_id, preview_path=str(preview_path))
            self._refresh_workspace_item_tree(kind, item_id)
