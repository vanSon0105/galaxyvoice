from __future__ import annotations

import json
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from ..common.paths import studio_root
from .batch import (
    OmniVoiceBatchItem,
    generate_omnivoice_batch,
    parse_batch_items,
    split_long_form,
)
from .features import MODE_LABELS, NON_VERBAL_TAGS
from .models import AUTO_MODE, OmniVoiceGenerationOptions
from .runtime import inspect_runtime


class OmniVoiceAdvancedGuiMixin:
    def _build_omnivoice_batch_tab(self, notebook: ttk.Notebook) -> None:
        page, text_widget, controls = self._build_omnivoice_bulk_page(
            notebook,
            "Batch Voice",
            self.omnivoice_batch_mode,
            self.omnivoice_batch_project_name,
            combine=False,
        )
        self.omnivoice_batch_tab = page
        self.omnivoice_batch_text = text_widget

        tools = ttk.Frame(page, style="Surface.TFrame")
        tools.grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(6, 0))
        tools.columnconfigure((0, 1, 2), weight=1)
        load_button = ttk.Button(tools, text="Nạp JSONL", command=self._load_omnivoice_jsonl)
        load_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        save_button = ttk.Button(tools, text="Lưu JSONL", command=self._save_omnivoice_jsonl)
        save_button.grid(row=0, column=1, sticky="ew", padx=3)
        sample_button = ttk.Button(tools, text="Tạo mẫu", command=self._insert_omnivoice_batch_sample)
        sample_button.grid(row=0, column=2, sticky="ew", padx=(3, 0))
        self.omnivoice_mutable_widgets.extend((load_button, save_button, sample_button))
        controls.configure(padding=(12, 12, 12, 12))

    def _build_omnivoice_long_form_tab(self, notebook: ttk.Notebook) -> None:
        page, text_widget, _controls = self._build_omnivoice_bulk_page(
            notebook,
            "Long-form",
            self.omnivoice_long_form_mode,
            self.omnivoice_long_form_project_name,
            combine=True,
        )
        self.omnivoice_long_form_tab = page
        self.omnivoice_long_form_text = text_widget

    def _build_omnivoice_bulk_page(
        self,
        notebook: ttk.Notebook,
        title: str,
        mode_variable: tk.StringVar,
        project_variable: tk.StringVar,
        *,
        combine: bool,
    ) -> tuple[ttk.Frame, tk.Text, ttk.Frame]:
        page = ttk.Frame(notebook, padding=12)
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2, minsize=330)
        page.rowconfigure(0, weight=1)
        notebook.add(page, text=title)

        editor = ttk.Frame(page, style="Panel.TFrame", padding=8)
        editor.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(0, weight=1)
        text_widget = tk.Text(
            editor,
            wrap="word",
            font=("Consolas" if not combine else "Segoe UI", 10),
            relief="flat",
            padx=10,
            pady=10,
            undo=True,
        )
        text_widget.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(editor, orient="vertical", command=text_widget.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text_widget.configure(yscrollcommand=scroll.set)
        self.omnivoice_mutable_widgets.append(text_widget)

        controls = ttk.Frame(page, style="Panel.TFrame", padding=12)
        controls.grid(row=0, column=1, rowspan=2, sticky="nsew")
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)
        row = 0
        ttk.Label(controls, text="Chế độ giọng", style="Section.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        row += 1
        mode_combo = ttk.Combobox(
            controls,
            textvariable=mode_variable,
            values=tuple(MODE_LABELS),
            state="readonly",
        )
        mode_combo.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        row += 1
        ttk.Label(controls, text="Profile đã lưu", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        profile_combo = ttk.Combobox(
            controls,
            textvariable=self.omnivoice_profile_choice,
            state="readonly",
        )
        profile_combo.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(3, 8))
        self.omnivoice_profile_combos.append(profile_combo)
        row += 1
        ttk.Label(controls, text="Ngôn ngữ", style="Panel.TLabel").grid(
            row=row, column=0, sticky="w"
        )
        language_combo = ttk.Combobox(
            controls,
            textvariable=self.omnivoice_language,
            values=self.omnivoice_language_values,
            state="normal",
        )
        language_combo.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
        self.omnivoice_editable_combos.append(language_combo)
        self.omnivoice_language_combos.append(language_combo)
        row += 1
        if combine:
            ttk.Label(controls, text="Khoảng nghỉ giữa phần (ms)", style="Panel.TLabel").grid(
                row=row, column=0, sticky="w", pady=2
            )
            gap_entry = ttk.Entry(controls, textvariable=self.omnivoice_long_form_gap_ms)
            gap_entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
            self.omnivoice_mutable_widgets.append(gap_entry)
            row += 1
        ttk.Label(controls, text="Tên project", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        row += 1
        project_entry = ttk.Entry(controls, textvariable=project_variable)
        project_entry.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(3, 8))
        row += 1
        ttk.Label(controls, text="Thư mục output", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        output_entry = ttk.Entry(controls, textvariable=self.omnivoice_output_dir)
        output_entry.grid(row=row, column=0, sticky="ew", pady=(3, 8))
        output_button = ttk.Button(controls, text="Chọn", command=self._browse_omnivoice_output)
        output_button.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=(3, 8))
        row += 1
        actions = ttk.Frame(controls, style="Surface.TFrame")
        actions.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        actions.columnconfigure((0, 1), weight=1)
        generate = ttk.Button(
            actions,
            text="Tạo long-form" if combine else "Chạy batch",
            style="Accent.TButton",
            command=lambda should_combine=combine: self._start_omnivoice_bulk(should_combine),
        )
        generate.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        stop = ttk.Button(actions, text="Dừng", command=self._stop_omnivoice, state="disabled")
        stop.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        play = ttk.Button(
            actions,
            text="Nghe",
            command=self._play_omnivoice_result,
            state="disabled",
        )
        play.grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=(6, 0))
        open_button = ttk.Button(
            actions,
            text="Mở output",
            command=self._open_omnivoice_output,
            state="disabled",
        )
        open_button.grid(row=1, column=1, sticky="ew", padx=(3, 0), pady=(6, 0))
        row += 1
        progress = ttk.Progressbar(controls, mode="indeterminate")
        progress.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        row += 1
        ttk.Label(controls, textvariable=self.omnivoice_job_status, style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )

        self.omnivoice_mutable_widgets.extend(
            (mode_combo, profile_combo, language_combo, project_entry, output_entry, output_button)
        )
        self.omnivoice_generate_buttons.append(generate)
        self.omnivoice_stop_buttons.append(stop)
        self.omnivoice_play_buttons.append(play)
        self.omnivoice_open_buttons.append(open_button)
        self.omnivoice_progress_bars.append(progress)
        return page, text_widget, controls

    def _build_omnivoice_lora_tab(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=12)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        notebook.add(page, text="LoRA")
        self.omnivoice_lora_tab = page

        settings = ttk.Frame(page, style="Panel.TFrame", padding=12)
        settings.grid(row=0, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)
        fields = (
            ("Base model", self.omnivoice_model_id),
            ("LoRA adapter", self.omnivoice_lora_adapter),
            ("Model sau khi merge", self.omnivoice_lora_merge_output),
        )
        entries: list[ttk.Entry] = []
        for row, (label, variable) in enumerate(fields):
            ttk.Label(settings, text=label, style="Panel.TLabel").grid(
                row=row, column=0, sticky="w", pady=3
            )
            entry = ttk.Entry(settings, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=3)
            entries.append(entry)
        actions = ttk.Frame(settings, style="Surface.TFrame")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        actions.columnconfigure((0, 1, 2, 3), weight=1)
        adapter_button = ttk.Button(actions, text="Chọn adapter", command=self._browse_omnivoice_lora)
        adapter_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        output_button = ttk.Button(
            actions, text="Chọn output", command=self._browse_omnivoice_lora_output
        )
        output_button.grid(row=0, column=1, sticky="ew", padx=3)
        merge_button = ttk.Button(
            actions,
            text="Merge LoRA",
            style="Accent.TButton",
            command=self._start_omnivoice_lora_merge,
        )
        merge_button.grid(row=0, column=2, sticky="ew", padx=3)
        stop_button = ttk.Button(
            actions,
            text="Dừng",
            command=self._stop_omnivoice,
            state="disabled",
        )
        stop_button.grid(row=0, column=3, sticky="ew", padx=(3, 0))
        self.omnivoice_mutable_widgets.extend(
            (*entries, adapter_button, output_button, merge_button)
        )
        self.omnivoice_stop_buttons.append(stop_button)
        ttk.Label(page, textvariable=self.omnivoice_lora_status, style="Panel.TLabel").grid(
            row=1, column=0, sticky="nw", pady=(10, 0)
        )

    def _start_omnivoice_bulk(self, combine: bool) -> None:
        if self._active_task is not None:
            return
        status = inspect_runtime(self.omnivoice_runtime)
        if not status.installed:
            messagebox.showerror("OmniVoice chưa được cài", status.message)
            self._select_omnivoice_runtime()
            return
        mode_variable = self.omnivoice_long_form_mode if combine else self.omnivoice_batch_mode
        mode = MODE_LABELS.get(mode_variable.get(), AUTO_MODE)
        source_widget = self.omnivoice_long_form_text if combine else self.omnivoice_batch_text
        project_variable = (
            self.omnivoice_long_form_project_name if combine else self.omnivoice_batch_project_name
        )
        try:
            items = (
                split_long_form(source_widget.get("1.0", "end"))
                if combine
                else parse_batch_items(source_widget.get("1.0", "end"))
            )
            options = self._omnivoice_options(
                mode,
                items[0].text,
                bulk=True,
                project_name=project_variable.get().strip()
                or ("omnivoice-long-form" if combine else "omnivoice-batch"),
            )
        except (OSError, ValueError) as error:
            messagebox.showerror("Thiết lập chưa hợp lệ", str(error))
            return
        gap_ms = self._safe_int(self.omnivoice_long_form_gap_ms, 250) if combine else 0
        self._start_omnivoice_thread(
            "omnivoice_long_form" if combine else "omnivoice_batch",
            self._run_omnivoice_bulk,
            (options, items, combine, gap_ms),
            "omnivoice-long-form" if combine else "omnivoice-batch",
        )

    def _run_omnivoice_bulk(
        self,
        options: OmniVoiceGenerationOptions,
        items: tuple[OmniVoiceBatchItem, ...],
        combine: bool,
        gap_ms: int,
    ) -> None:
        try:
            result = generate_omnivoice_batch(
                options,
                items,
                self.omnivoice_client,
                combine=combine,
                gap_ms=gap_ms,
                progress=lambda message: self.events.put(("omnivoice_progress", message)),
            )
        except Exception as error:
            event = "omnivoice_cancelled" if self._omnivoice_cancel_requested else "omnivoice_error"
            self.events.put((event, error))
        else:
            self.events.put(("omnivoice_batch_done", result))

    def _start_omnivoice_lora_merge(self) -> None:
        if self._active_task is not None:
            return
        status = inspect_runtime(self.omnivoice_runtime)
        if not status.installed:
            messagebox.showerror("OmniVoice chưa được cài", status.message)
            return
        base_model = self.omnivoice_model_id.get().strip()
        adapter = self.omnivoice_lora_adapter.get().strip()
        output_dir = self.omnivoice_lora_merge_output.get().strip()
        if not base_model or not adapter or not output_dir:
            messagebox.showerror(
                "Thiếu thiết lập LoRA",
                "Hãy chọn base model, adapter và thư mục model sau khi merge.",
            )
            return
        self._start_omnivoice_thread(
            "omnivoice_lora_merge",
            self._run_omnivoice_lora_merge,
            (base_model, adapter, output_dir),
            "omnivoice-lora-merge",
        )

    def _run_omnivoice_lora_merge(
        self,
        base_model: str,
        adapter: str,
        output_dir: str,
    ) -> None:
        try:
            payload = self.omnivoice_client.request(
                "merge_lora",
                {
                    "base_model": base_model,
                    "lora_adapter": adapter,
                    "output_dir": output_dir,
                },
                on_progress=lambda message: self.events.put(("omnivoice_progress", message)),
            )
        except Exception as error:
            event = "omnivoice_cancelled" if self._omnivoice_cancel_requested else "omnivoice_error"
            self.events.put((event, error))
        else:
            self.events.put(("omnivoice_lora_merged", payload))

    def _install_omnivoice_flashinfer(self) -> None:
        installer = studio_root() / "install_omnivoice_flashinfer.ps1"
        if not installer.is_file():
            messagebox.showerror("Thiếu bộ cài", f"Không tìm thấy {installer}")
            return
        self.omnivoice_client.stop()
        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(installer),
                ],
                cwd=str(studio_root()),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError as error:
            messagebox.showerror("Không mở được bộ cài", str(error))
            return
        self._append_omnivoice_log("Đã mở cửa sổ cài FlashInfer.")

    def _browse_omnivoice_lora(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.omnivoice_runtime.root)
        if selected:
            self.omnivoice_lora_adapter.set(selected)

    def _browse_omnivoice_lora_output(self) -> None:
        selected = filedialog.askdirectory(
            initialdir=self.omnivoice_lora_merge_output.get() or self.omnivoice_runtime.models_dir,
            mustexist=False,
        )
        if selected:
            self.omnivoice_lora_merge_output.set(selected)

    def _insert_omnivoice_expression(self, mode: str) -> None:
        widget = self.omnivoice_text_widgets[mode]
        tag = NON_VERBAL_TAGS.get(self.omnivoice_expression_choice.get(), "[laughter]")
        widget.insert("insert", f"{tag} ")
        widget.focus_set()

    def _insert_omnivoice_pronunciation(self, mode: str, kind: str) -> None:
        title = "Phát âm CMU" if kind == "cmu" else "Pinyin có thanh điệu"
        prompt = "Nhập phoneme, ví dụ B EY1 S" if kind == "cmu" else "Nhập pinyin, ví dụ ZHE2"
        value = simpledialog.askstring(title, prompt, parent=self.root)
        if not value or not value.strip():
            return
        replacement = f"[{value.strip().upper()}]" if kind == "cmu" else value.strip().upper()
        widget = self.omnivoice_text_widgets[mode]
        try:
            start = widget.index("sel.first")
            end = widget.index("sel.last")
        except tk.TclError:
            widget.insert("insert", replacement)
        else:
            widget.delete(start, end)
            widget.insert(start, replacement)
        widget.focus_set()

    def _load_omnivoice_jsonl(self) -> None:
        selected = filedialog.askopenfilename(
            filetypes=[("JSON Lines", "*.jsonl"), ("Text", "*.txt"), ("All files", "*.*")]
        )
        if not selected:
            return
        try:
            content = Path(selected).read_text(encoding="utf-8")
            parse_batch_items(content)
        except (OSError, UnicodeDecodeError, ValueError) as error:
            messagebox.showerror("Không nạp được batch", str(error))
            return
        self.omnivoice_batch_text.delete("1.0", "end")
        self.omnivoice_batch_text.insert("1.0", content)

    def _save_omnivoice_jsonl(self) -> None:
        content = self.omnivoice_batch_text.get("1.0", "end").strip()
        try:
            items = parse_batch_items(content)
        except ValueError as error:
            messagebox.showerror("Batch chưa hợp lệ", str(error))
            return
        selected = filedialog.asksaveasfilename(
            defaultextension=".jsonl",
            filetypes=[("JSON Lines", "*.jsonl")],
        )
        if not selected:
            return
        lines = [
            json.dumps(
                {
                    "id": item.item_id,
                    "text": item.text,
                    "language_id": item.language or self.omnivoice_language.get().strip(),
                    "speed": item.speed,
                    "duration": item.duration,
                },
                ensure_ascii=False,
            )
            for item in items
        ]
        try:
            Path(selected).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as error:
            messagebox.showerror("Không lưu được JSONL", str(error))

    def _insert_omnivoice_batch_sample(self) -> None:
        sample = (
            '{"id":"intro","text":"Xin chào","language_id":"vi","speed":1.0}\n'
            '{"id":"outro","text":"Cảm ơn bạn đã lắng nghe","language_id":"vi"}\n'
        )
        self.omnivoice_batch_text.delete("1.0", "end")
        self.omnivoice_batch_text.insert("1.0", sample)
