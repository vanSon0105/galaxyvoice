from __future__ import annotations

import os
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from ..common.paths import studio_root
from ..common.processes import managed_media_processes
from ..common.theme import PALETTE, text_widget_options
from .service import (
    AUDIO_OUTPUT_FORMATS,
    AUDIO_PROCESS_METHOD_LABELS,
    AUDIO_PROCESSING_DEVICE_LABELS,
    AUDIO_SAVED_SETTINGS,
    CPU_AUDIO_DEVICE,
    DEMUCS_METHOD,
    MDX_METHOD,
    VR_METHOD,
    AudioSeparationOptions,
    UVRModel,
    audio_device_code,
    audio_device_label,
    audio_method_code,
    audio_method_label,
    audio_separator_runtime_ready,
    default_audio_separator_runtime,
    default_uvr_root,
    resolve_audio_device,
    save_audio_presets,
    separate_audio,
)


class AudioSeparationTabMixin:
    def _build_audio_separation_tab(self) -> None:
        self.audio_tab = ttk.Frame(self.main_notebook, padding=(0, 10, 0, 0))
        self.audio_tab.columnconfigure(0, weight=1)
        self.audio_tab.rowconfigure(0, weight=1)
        self.main_notebook.add(self.audio_tab, text="Tách âm thanh")

        panel = ttk.Frame(self.audio_tab, style="Panel.TFrame", padding=14)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(5, weight=1)

        paths = ttk.Frame(panel, style="Surface.TFrame")
        paths.grid(row=0, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        self.audio_input_button = ttk.Button(
            paths,
            text="Select Input",
            command=self.browse_audio_input,
            width=16,
        )
        self.audio_input_button.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 6))
        self.audio_input_entry = ttk.Entry(paths, textvariable=self.audio_input_path)
        self.audio_input_entry.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        self.audio_input_browse_button = ttk.Button(
            paths,
            text="Browse",
            command=self.browse_audio_input,
            width=10,
        )
        self.audio_input_browse_button.grid(row=0, column=2, padx=(8, 0), pady=(0, 6))

        self.audio_output_button = ttk.Button(
            paths,
            text="Select Output",
            command=self.browse_audio_output,
            width=16,
        )
        self.audio_output_button.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.audio_output_entry = ttk.Entry(paths, textvariable=self.audio_output_dir)
        self.audio_output_entry.grid(row=1, column=1, sticky="ew")
        self.audio_output_browse_button = ttk.Button(
            paths,
            text="Browse",
            command=self.browse_audio_output,
            width=10,
        )
        self.audio_output_browse_button.grid(row=1, column=2, padx=(8, 0))

        format_row = ttk.Frame(panel, style="Surface.TFrame")
        format_row.grid(row=1, column=0, sticky="e", pady=(10, 4))
        self.audio_format_buttons: list[ttk.Radiobutton] = []
        for column, output_format in enumerate(AUDIO_OUTPUT_FORMATS):
            button = ttk.Radiobutton(
                format_row,
                text=output_format,
                value=output_format,
                variable=self.audio_format,
            )
            button.grid(row=0, column=column, padx=(12 if column else 0, 0))
            self.audio_format_buttons.append(button)

        options = ttk.Frame(panel, style="Surface.TFrame")
        options.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        for column in range(3):
            options.columnconfigure(column, weight=1, uniform="audio-options")

        ttk.Label(options, text="Choose Process Method", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(options, textvariable=self.audio_segment_label, style="Panel.TLabel").grid(
            row=0, column=1, sticky="w", padx=(12, 0)
        )
        ttk.Label(options, textvariable=self.audio_overlap_label, style="Panel.TLabel").grid(
            row=0, column=2, sticky="w", padx=(12, 0)
        )
        self.audio_method_combo = ttk.Combobox(
            options,
            textvariable=self.audio_method,
            values=tuple(AUDIO_PROCESS_METHOD_LABELS.values()),
            state="readonly",
        )
        self.audio_method_combo.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.audio_method_combo.bind("<<ComboboxSelected>>", self._on_audio_method_changed)
        self.audio_segment_combo = ttk.Combobox(
            options,
            textvariable=self.audio_segment_size,
            state="readonly",
        )
        self.audio_segment_combo.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(4, 0))
        self.audio_overlap_combo = ttk.Combobox(
            options,
            textvariable=self.audio_overlap,
            state="readonly",
        )
        self.audio_overlap_combo.grid(row=1, column=2, sticky="ew", padx=(12, 0), pady=(4, 0))

        ttk.Label(options, text="Choose Model", style="Panel.TLabel").grid(
            row=2, column=0, sticky="w", pady=(12, 0)
        )
        ttk.Label(options, text="Processing Device", style="Panel.TLabel").grid(
            row=2, column=1, sticky="w", padx=(12, 0), pady=(12, 0)
        )
        ttk.Label(options, text="Select Saved Settings", style="Panel.TLabel").grid(
            row=2, column=2, sticky="w", padx=(12, 0), pady=(12, 0)
        )
        self.audio_model_combo = ttk.Combobox(
            options,
            textvariable=self.audio_model,
            state="readonly",
        )
        self.audio_model_combo.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.audio_device_combo = ttk.Combobox(
            options,
            textvariable=self.audio_processing_device,
            values=tuple(AUDIO_PROCESSING_DEVICE_LABELS.values()),
            state="readonly" if self.audio_gpu_conversion.get() else "disabled",
        )
        self.audio_device_combo.grid(row=3, column=1, sticky="ew", padx=(12, 0), pady=(4, 0))
        self.audio_preset_combo = ttk.Combobox(
            options,
            textvariable=self.audio_saved_setting,
            values=self._audio_preset_names(),
            state="readonly",
        )
        self.audio_preset_combo.grid(row=3, column=2, sticky="ew", padx=(12, 0), pady=(4, 0))
        self.audio_preset_combo.bind("<<ComboboxSelected>>", self._on_audio_preset_changed)

        flags = ttk.Frame(panel, style="Surface.TFrame")
        flags.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        for column in range(4):
            flags.columnconfigure(column, weight=1)
        self.audio_gpu_check = ttk.Checkbutton(
            flags,
            text="GPU Conversion",
            variable=self.audio_gpu_conversion,
            command=self._on_audio_gpu_changed,
        )
        self.audio_gpu_check.grid(row=0, column=0, sticky="w")
        self.audio_vocals_check = ttk.Checkbutton(
            flags,
            text="Vocals Only",
            variable=self.audio_vocals_only,
            command=self._on_audio_vocals_changed,
        )
        self.audio_vocals_check.grid(row=0, column=1, sticky="w")
        self.audio_instrumental_check = ttk.Checkbutton(
            flags,
            text="Instrumental Only",
            variable=self.audio_instrumental_only,
            command=self._on_audio_instrumental_changed,
        )
        self.audio_instrumental_check.grid(row=0, column=2, sticky="w")
        self.audio_sample_check = ttk.Checkbutton(
            flags,
            text="Sample Mode (30s)",
            variable=self.audio_sample_mode,
        )
        self.audio_sample_check.grid(row=0, column=3, sticky="w")

        actions = ttk.Frame(panel, style="Surface.TFrame")
        actions.grid(row=4, column=0, sticky="ew", pady=(10, 8))
        actions.columnconfigure(1, weight=1)
        self.audio_settings_button = ttk.Button(
            actions,
            text="Settings",
            command=self.open_audio_settings,
            width=9,
        )
        self.audio_settings_button.grid(row=0, column=0, padx=(0, 8))
        self.audio_process_button = ttk.Button(
            actions,
            text="Start Processing",
            style="Accent.TButton",
            command=self.start_audio_separation,
        )
        self.audio_process_button.grid(row=0, column=1, sticky="ew")
        self.audio_open_button = ttk.Button(
            actions,
            text="Open Output",
            command=self.open_output,
            state="disabled",
        )
        self.audio_open_button.grid(row=0, column=2, padx=(8, 0))
        self.audio_stop_button = ttk.Button(
            actions,
            text="Stop",
            command=self.stop_audio_separation,
            state="disabled",
            width=7,
        )
        self.audio_stop_button.grid(row=0, column=3, padx=(8, 0))

        console_frame = ttk.Frame(panel, style="Surface.TFrame")
        console_frame.grid(row=5, column=0, sticky="nsew")
        console_frame.columnconfigure(0, weight=1)
        console_frame.rowconfigure(1, weight=1)
        self.audio_progress = ttk.Progressbar(console_frame, mode="indeterminate")
        self.audio_progress.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.audio_log_text = tk.Text(
            console_frame,
            height=5,
            wrap="word",
            font="TkFixedFont",
            padx=10,
            pady=8,
            **text_widget_options(log=True),
        )
        self.audio_log_text.grid(row=1, column=0, sticky="nsew")
        self.audio_log_text.configure(state="disabled")

        self.audio_mutable_widgets: tuple[tk.Widget, ...] = (
            self.audio_input_button,
            self.audio_input_entry,
            self.audio_input_browse_button,
            self.audio_output_button,
            self.audio_output_entry,
            self.audio_output_browse_button,
            self.audio_method_combo,
            self.audio_segment_combo,
            self.audio_overlap_combo,
            self.audio_model_combo,
            self.audio_preset_combo,
            self.audio_gpu_check,
            self.audio_vocals_check,
            self.audio_instrumental_check,
            self.audio_sample_check,
            self.audio_settings_button,
            *self.audio_format_buttons,
        )
        self._refresh_audio_method_controls(preserve_selection=True)

    def _audio_models_for_method(self, method: str | None = None) -> list[UVRModel]:
        method_code = audio_method_code(method or self.audio_method.get())
        return [model for model in self.audio_models if model.method == method_code]

    def _selected_audio_model(self) -> UVRModel | None:
        selected_label = self.audio_model.get()
        return next(
            (
                model
                for model in self._audio_models_for_method()
                if model.label == selected_label
            ),
            None,
        )

    def _refresh_audio_method_controls(self, *, preserve_selection: bool = False) -> None:
        method = audio_method_code(self.audio_method.get())
        current_model = self.audio_model.get() if preserve_selection else ""
        models = self._audio_models_for_method(method)
        model_labels = tuple(model.label for model in models)
        self.audio_model_combo.configure(values=model_labels)
        if current_model in model_labels:
            self.audio_model.set(current_model)
        elif models:
            self.audio_model.set(models[0].label)
        else:
            self.audio_model.set("")

        if method == VR_METHOD:
            self.audio_segment_label.set("Window Size")
            self.audio_overlap_label.set("Aggression")
            segment_values = ("320", "512", "1024")
            overlap_values = ("Default", "5", "10", "15", "20")
            segment_default = "512"
        elif method == DEMUCS_METHOD:
            self.audio_segment_label.set("Segment Size")
            self.audio_overlap_label.set("Overlap")
            segment_values = ("Default", "10", "20", "30", "40")
            overlap_values = ("Default", "0.10", "0.25", "0.50")
            segment_default = "Default"
        else:
            self.audio_segment_label.set("Segment Size")
            self.audio_overlap_label.set("Overlap")
            segment_values = ("Default", "32", "64", "128", "256", "512")
            overlap_values = ("Default", "0.10", "0.25", "0.50", "0.75")
            segment_default = "256"

        self.audio_segment_combo.configure(values=segment_values)
        self.audio_overlap_combo.configure(values=overlap_values)
        if self.audio_segment_size.get() not in segment_values:
            self.audio_segment_size.set(segment_default)
        if self.audio_overlap.get() not in overlap_values:
            self.audio_overlap.set("Default")

    def _on_audio_method_changed(self, _event: tk.Event | None = None) -> None:
        self._refresh_audio_method_controls()

    def _on_audio_gpu_changed(self) -> None:
        busy = bool(self.worker and self.worker.is_alive())
        self.audio_device_combo.configure(
            state="readonly" if self.audio_gpu_conversion.get() and not busy else "disabled"
        )

    def _on_audio_vocals_changed(self) -> None:
        if self.audio_vocals_only.get():
            self.audio_instrumental_only.set(False)

    def _on_audio_instrumental_changed(self) -> None:
        if self.audio_instrumental_only.get():
            self.audio_vocals_only.set(False)

    def _select_audio_model_filename(self, filename: str) -> None:
        model = next(
            (
                candidate
                for candidate in self._audio_models_for_method()
                if candidate.filename == filename
            ),
            None,
        )
        if model is not None:
            self.audio_model.set(model.label)

    def _on_audio_preset_changed(self, _event: tk.Event | None = None) -> None:
        preset = self.audio_saved_setting.get()
        custom = self.audio_custom_presets.get(preset)
        if custom is not None:
            self.audio_method.set(audio_method_label(str(custom.get("method", MDX_METHOD))))
            self._refresh_audio_method_controls()
            self._select_audio_model_filename(str(custom.get("model_filename", "")))
            output_format = str(custom.get("output_format", "WAV")).upper()
            if output_format in AUDIO_OUTPUT_FORMATS:
                self.audio_format.set(output_format)
            self.audio_segment_size.set(str(custom.get("segment_size", self.audio_segment_size.get())))
            self.audio_overlap.set(str(custom.get("overlap", self.audio_overlap.get())))
            self.audio_processing_device.set(
                audio_device_label(str(custom.get("processing_device", "auto")))
            )
            self.audio_gpu_conversion.set(bool(custom.get("gpu_conversion", True)))
            self.audio_vocals_only.set(bool(custom.get("vocals_only", False)))
            self.audio_instrumental_only.set(bool(custom.get("instrumental_only", False)))
            if self.audio_vocals_only.get() and self.audio_instrumental_only.get():
                self.audio_instrumental_only.set(False)
            self.audio_sample_mode.set(bool(custom.get("sample_mode", False)))
            self._on_audio_gpu_changed()
        elif preset == "Vocal extraction":
            self.audio_method.set(audio_method_label(MDX_METHOD))
            self._refresh_audio_method_controls()
            self._select_audio_model_filename("Kim_Vocal_2.onnx")
            self.audio_vocals_only.set(True)
            self.audio_instrumental_only.set(False)
        elif preset == "Instrumental / Karaoke":
            self.audio_method.set(audio_method_label(MDX_METHOD))
            self._refresh_audio_method_controls()
            self._select_audio_model_filename("UVR-MDX-NET-Inst_HQ_5.onnx")
            self.audio_vocals_only.set(False)
            self.audio_instrumental_only.set(True)
        elif preset == "Denoise":
            self.audio_method.set(audio_method_label(VR_METHOD))
            self._refresh_audio_method_controls()
            self._select_audio_model_filename("UVR-DeNoise-Lite.pth")
            self.audio_vocals_only.set(False)
            self.audio_instrumental_only.set(False)
        else:
            self.audio_method.set(audio_method_label(MDX_METHOD))
            self._refresh_audio_method_controls()
            self._select_audio_model_filename("Kim_Vocal_2.onnx")
            self.audio_vocals_only.set(False)
            self.audio_instrumental_only.set(False)

    def _audio_preset_names(self) -> tuple[str, ...]:
        return (*AUDIO_SAVED_SETTINGS, *sorted(self.audio_custom_presets, key=str.casefold))

    def save_current_audio_preset(self, parent: tk.Misc | None = None) -> None:
        name = simpledialog.askstring(
            "Save Audio Preset",
            "Preset name:",
            parent=parent or self.root,
        )
        if not name or not name.strip():
            return
        name = name.strip()
        if name in AUDIO_SAVED_SETTINGS:
            messagebox.showerror("Reserved preset", "Choose a different name for the custom preset.")
            return
        if name in self.audio_custom_presets and not messagebox.askyesno(
            "Replace preset",
            f"Replace the saved preset '{name}'?",
            parent=parent or self.root,
        ):
            return
        model = self._selected_audio_model()
        preset = {
            "method": audio_method_code(self.audio_method.get()),
            "model_filename": model.filename if model else "",
            "output_format": self.audio_format.get(),
            "segment_size": self.audio_segment_size.get(),
            "overlap": self.audio_overlap.get(),
            "processing_device": audio_device_code(self.audio_processing_device.get()),
            "gpu_conversion": bool(self.audio_gpu_conversion.get()),
            "vocals_only": bool(self.audio_vocals_only.get()),
            "instrumental_only": bool(self.audio_instrumental_only.get()),
            "sample_mode": bool(self.audio_sample_mode.get()),
        }
        updated_presets = {**self.audio_custom_presets, name: preset}
        try:
            save_audio_presets(self.audio_presets_path, updated_presets)
        except OSError as error:
            messagebox.showerror("Could not save preset", str(error), parent=parent or self.root)
            return
        self.audio_custom_presets = updated_presets
        self.audio_preset_combo.configure(values=self._audio_preset_names())
        self.audio_saved_setting.set(name)
        self._append_audio_log(f"Đã lưu preset: {name}")

    def delete_audio_preset(self, parent: tk.Misc | None = None) -> None:
        name = self.audio_saved_setting.get()
        if name not in self.audio_custom_presets:
            messagebox.showinfo(
                "Built-in preset",
                "Only custom presets can be deleted.",
                parent=parent or self.root,
            )
            return
        if not messagebox.askyesno(
            "Delete preset",
            f"Delete the saved preset '{name}'?",
            parent=parent or self.root,
        ):
            return
        updated_presets = {
            preset_name: settings
            for preset_name, settings in self.audio_custom_presets.items()
            if preset_name != name
        }
        try:
            save_audio_presets(self.audio_presets_path, updated_presets)
        except OSError as error:
            messagebox.showerror("Could not delete preset", str(error), parent=parent or self.root)
            return
        self.audio_custom_presets = updated_presets
        self.audio_preset_combo.configure(values=self._audio_preset_names())
        self.audio_saved_setting.set("Default")
        self._on_audio_preset_changed()
        self._append_audio_log(f"Đã xóa preset: {name}")

    def browse_audio_input(self) -> None:
        current = self.audio_input_path.get().strip()
        file_path = filedialog.askopenfilename(
            initialdir=str(Path(current).parent) if current else str(Path.cwd()),
            filetypes=[
                ("Media files", "*.wav *.flac *.mp3 *.m4a *.aac *.ogg *.wma *.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("Audio files", "*.wav *.flac *.mp3 *.m4a *.aac *.ogg *.wma"),
                ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("All files", "*.*"),
            ],
        )
        if file_path:
            self.audio_input_path.set(file_path)

    def browse_audio_output(self) -> None:
        folder = filedialog.askdirectory(
            initialdir=self.audio_output_dir.get() or self.output_dir.get() or str(Path.cwd())
        )
        if folder:
            self.audio_output_dir.set(folder)

    def open_audio_settings(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Audio Separator Settings")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=16)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)

        uvr_root = default_uvr_root()
        runtime = default_audio_separator_runtime()
        selected_device = (
            audio_device_code(self.audio_processing_device.get())
            if self.audio_gpu_conversion.get()
            else CPU_AUDIO_DEVICE
        )
        selected_method = audio_method_code(self.audio_method.get())
        try:
            resolved_device = resolve_audio_device(selected_device, selected_method)
            ready, runtime_status = audio_separator_runtime_ready(
                runtime,
                resolved_device,
                selected_method,
            )
        except RuntimeError as error:
            ready, runtime_status = False, str(error)
        model_count = len(self.audio_models)
        ttk.Label(body, text="Ultimate Vocal Remover", style="PageSection.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(body, text=str(uvr_root), wraplength=self._px(620)).grid(
            row=1, column=0, sticky="w", pady=(4, 12)
        )
        ttk.Label(body, text=f"Models detected: {model_count}").grid(row=2, column=0, sticky="w")
        ttk.Label(body, text="Audio separator runtime", style="PageSection.TLabel").grid(
            row=3, column=0, sticky="w", pady=(14, 0)
        )
        ttk.Label(body, text=str(runtime.python_path), wraplength=self._px(620)).grid(
            row=4, column=0, sticky="w", pady=(4, 4)
        )
        ttk.Label(
            body,
            text=runtime_status,
            foreground=PALETTE.success if ready else PALETTE.danger,
            wraplength=self._px(620),
        ).grid(row=5, column=0, sticky="w")

        ttk.Label(body, text="Saved Settings", style="PageSection.TLabel").grid(
            row=6, column=0, sticky="w", pady=(14, 0)
        )
        preset_actions = ttk.Frame(body)
        preset_actions.grid(row=7, column=0, sticky="w", pady=(6, 0))
        ttk.Button(
            preset_actions,
            text="Save Current Preset",
            command=lambda: self.save_current_audio_preset(dialog),
        ).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(
            preset_actions,
            text="Delete Selected Preset",
            command=lambda: self.delete_audio_preset(dialog),
        ).grid(row=0, column=1)

        actions = ttk.Frame(body)
        actions.grid(row=8, column=0, sticky="ew", pady=(16, 0))
        actions.columnconfigure(2, weight=1)
        ttk.Button(actions, text="Open UVR Folder", command=self.open_uvr_folder).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(actions, text="Install / Update Engine", command=self.install_audio_separator).grid(
            row=0, column=1
        )
        ttk.Button(actions, text="Close", command=dialog.destroy).grid(row=0, column=3)
        dialog.grab_set()

    def open_uvr_folder(self) -> None:
        uvr_root = default_uvr_root()
        if not uvr_root.is_dir():
            messagebox.showerror("UVR folder missing", f"Could not find: {uvr_root}")
            return
        os.startfile(uvr_root)

    def install_audio_separator(self) -> None:
        installer = studio_root() / "install_audio_separator.ps1"
        if not installer.is_file():
            messagebox.showerror("Installer missing", f"Could not find: {installer}")
            return
        device = (
            audio_device_code(self.audio_processing_device.get())
            if self.audio_gpu_conversion.get()
            else CPU_AUDIO_DEVICE
        )
        command = [
            "powershell",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(installer),
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
        self._append_audio_log("Đã mở bộ cài audio separator ở cửa sổ riêng.")

    def start_audio_separation(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        input_value = self.audio_input_path.get().strip()
        if not input_value:
            messagebox.showwarning("Missing input", "Choose an audio or video file first.")
            return
        input_path = Path(input_value).expanduser()
        if not input_path.is_file():
            messagebox.showerror("Input not found", f"Could not find: {input_path}")
            return
        model = self._selected_audio_model()
        if model is None:
            messagebox.showerror(
                "Model missing",
                "No compatible model was found in the local Ultimate Vocal Remover folder.",
            )
            return
        processing_device = (
            audio_device_code(self.audio_processing_device.get())
            if self.audio_gpu_conversion.get()
            else CPU_AUDIO_DEVICE
        )
        method = audio_method_code(self.audio_method.get())
        try:
            resolved_device = resolve_audio_device(processing_device, method)
        except RuntimeError as error:
            messagebox.showerror("Processing device unavailable", str(error))
            return
        runtime = default_audio_separator_runtime()
        ready, runtime_status = audio_separator_runtime_ready(
            runtime,
            resolved_device,
            method,
        )
        if not ready:
            install_now = messagebox.askyesno(
                "Audio separator chưa được cài",
                f"{runtime_status}\n\nMở bộ cài engine ngay?",
            )
            if install_now:
                self.install_audio_separator()
            return

        options = AudioSeparationOptions(
            input_path=input_path,
            output_dir=Path(self.audio_output_dir.get().strip() or self.output_dir.get()).expanduser(),
            project_name=f"{input_path.stem}-separated",
            method=audio_method_code(self.audio_method.get()),
            model_filename=model.filename,
            output_format=self.audio_format.get(),
            segment_size=self.audio_segment_size.get(),
            overlap=self.audio_overlap.get(),
            processing_device=processing_device,
            vocals_only=bool(self.audio_vocals_only.get()),
            instrumental_only=bool(self.audio_instrumental_only.get()),
            sample_mode=bool(self.audio_sample_mode.get()),
        )

        managed_media_processes.reset()
        self._audio_stop_event = threading.Event()
        self._active_task = "audio_separation"
        self.last_result = None
        self.audio_open_button.configure(state="disabled")
        self._clear_audio_log()
        self._set_busy(True)
        self.audio_progress.start(12)
        self.status.set("Separating audio")
        self._append_audio_log("Bắt đầu tách âm thanh...")
        self.worker = threading.Thread(
            target=self._run_audio_separation,
            args=(options, self._audio_stop_event),
            daemon=True,
        )
        self.worker.start()

    def _run_audio_separation(
        self,
        options: AudioSeparationOptions,
        stop_event: threading.Event,
    ) -> None:
        try:
            result = separate_audio(
                options,
                progress=lambda message: self.events.put(("audio_log", message)),
                stop_event=stop_event,
            )
            self.events.put(("done", result))
        except Exception as error:  # pragma: no cover - UI boundary
            event = "audio_cancelled" if stop_event.is_set() else "error"
            self.events.put((event, error))
        finally:
            managed_media_processes.reset()

    def stop_audio_separation(self) -> None:
        if self._active_task != "audio_separation":
            return
        self.status.set("Stopping audio separation")
        self._append_audio_log("Đang dừng tác vụ...")
        self._audio_stop_event.set()
        managed_media_processes.terminate_all()

    def _append_audio_log(self, message: str) -> None:
        self.audio_log_text.configure(state="normal")
        self.audio_log_text.insert("end", f"{message}\n")
        self.audio_log_text.see("end")
        self.audio_log_text.configure(state="disabled")

    def _clear_audio_log(self) -> None:
        self.audio_log_text.configure(state="normal")
        self.audio_log_text.delete("1.0", "end")
        self.audio_log_text.configure(state="disabled")

    def _update_audio_progress_from_message(self, message: str) -> None:
        match = re.search(r"(?<!\d)(\d{1,3})%", message)
        if match is None:
            return
        percentage = max(0, min(100, int(match.group(1))))
        self.audio_progress.stop()
        self.audio_progress.configure(mode="determinate", maximum=100, value=percentage)
        self.status.set(f"Separating audio {percentage}%")
