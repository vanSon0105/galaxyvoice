from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .engine import GenerationOptions, GenerationResult, generate_package
from .tts import PowerShellSapiTTS, Voice


class GalaxyStudioApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Galaxy AI Voice & Subtitle Studio")
        self.root.geometry("1120x720")
        self.root.minsize(900, 600)

        self.tts = PowerShellSapiTTS()
        self.voices: list[Voice] = []
        self.worker: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.last_result: GenerationResult | None = None

        self.project_name = tk.StringVar(value="galaxy_project")
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "exports"))
        self.voice_name = tk.StringVar()
        self.rate = tk.IntVar(value=0)
        self.volume = tk.IntVar(value=100)
        self.pause_ms = tk.IntVar(value=250)
        self.max_chars = tk.IntVar(value=160)
        self.export_mp3 = tk.BooleanVar(value=True)
        self.keep_segments = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Ready")

        self._configure_style()
        self._build_layout()
        self._poll_events()
        self.refresh_voices()

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        self.root.configure(bg="#f4f1ea")
        style.configure(".", font=("Segoe UI", 10), background="#f4f1ea", foreground="#242424")
        style.configure("TFrame", background="#f4f1ea")
        style.configure("Panel.TFrame", background="#ffffff", borderwidth=1, relief="solid")
        style.configure("TLabel", background="#f4f1ea")
        style.configure("Panel.TLabel", background="#ffffff")
        style.configure("Header.TLabel", font=("Segoe UI Semibold", 15), background="#f4f1ea")
        style.configure("Section.TLabel", font=("Segoe UI Semibold", 10), background="#ffffff")
        style.configure("TButton", padding=(10, 6))
        style.configure("Accent.TButton", background="#145c54", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#1d756c"), ("disabled", "#9fa9a7")])
        style.configure("TCheckbutton", background="#ffffff")

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        shell = ttk.Frame(self.root, padding=16)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.columnconfigure(1, minsize=340)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Galaxy AI Voice & Subtitle Studio", style="Header.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, textvariable=self.status).grid(row=0, column=1, sticky="e")

        left = ttk.Frame(shell)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="Script").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.script_text = tk.Text(
            left,
            wrap="word",
            undo=True,
            font=("Segoe UI", 11),
            padx=14,
            pady=12,
            bg="#fffdfa",
            fg="#1f1f1f",
            insertbackground="#1f1f1f",
            relief="solid",
            bd=1,
        )
        self.script_text.grid(row=1, column=0, sticky="nsew")

        right = ttk.Frame(shell, style="Panel.TFrame", padding=14)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        self._build_project_panel(right)
        self._build_voice_panel(right)
        self._build_export_panel(right)

        actions = ttk.Frame(right, style="Panel.TFrame")
        actions.grid(row=9, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.generate_button = ttk.Button(actions, text="Generate", style="Accent.TButton", command=self.start_generate)
        self.generate_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.open_button = ttk.Button(actions, text="Open Output", command=self.open_output, state="disabled")
        self.open_button.grid(row=0, column=1, sticky="ew")

        self.progress = ttk.Progressbar(right, mode="indeterminate")
        self.progress.grid(row=10, column=0, sticky="ew", pady=(12, 0))

        log_frame = ttk.Frame(shell)
        log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        ttk.Label(log_frame, text="Log").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.log_text = tk.Text(
            log_frame,
            height=6,
            wrap="word",
            font=("Consolas", 9),
            bg="#202522",
            fg="#e9f1ec",
            relief="flat",
            padx=10,
            pady=8,
        )
        self.log_text.grid(row=1, column=0, sticky="ew")
        self.log_text.configure(state="disabled")

    def _build_project_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Project", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(parent, text="Name", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 2))
        ttk.Entry(parent, textvariable=self.project_name).grid(row=2, column=0, sticky="ew")

        ttk.Label(parent, text="Output folder", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 2))
        output_row = ttk.Frame(parent, style="Panel.TFrame")
        output_row.grid(row=4, column=0, sticky="ew")
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.output_dir).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(output_row, text="Browse", command=self.browse_output).grid(row=0, column=1)

    def _build_voice_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Voice", style="Section.TLabel").grid(row=5, column=0, sticky="w", pady=(18, 8))
        voice_row = ttk.Frame(parent, style="Panel.TFrame")
        voice_row.grid(row=6, column=0, sticky="ew")
        voice_row.columnconfigure(0, weight=1)
        self.voice_combo = ttk.Combobox(voice_row, textvariable=self.voice_name, state="readonly")
        self.voice_combo.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(voice_row, text="Refresh", command=self.refresh_voices).grid(row=0, column=1)

        sliders = ttk.Frame(parent, style="Panel.TFrame")
        sliders.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        sliders.columnconfigure(1, weight=1)
        self._add_slider(sliders, row=0, label="Speed", variable=self.rate, from_=-10, to=10)
        self._add_slider(sliders, row=1, label="Volume", variable=self.volume, from_=0, to=100)
        self._add_slider(sliders, row=2, label="Pause", variable=self.pause_ms, from_=0, to=1200)

    def _build_export_panel(self, parent: ttk.Frame) -> None:
        export = ttk.Frame(parent, style="Panel.TFrame")
        export.grid(row=8, column=0, sticky="ew", pady=(18, 0))
        export.columnconfigure(1, weight=1)
        ttk.Label(export, text="Subtitle", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(export, text="Max chars", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Spinbox(export, from_=60, to=260, increment=10, textvariable=self.max_chars, width=8).grid(
            row=1, column=1, sticky="e", pady=(10, 0)
        )
        ttk.Checkbutton(export, text="Export MP3 when ffmpeg is available", variable=self.export_mp3).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        ttk.Checkbutton(export, text="Keep segment WAV files", variable=self.keep_segments).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

    def _add_slider(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.IntVar,
        from_: int,
        to: int,
    ) -> None:
        value = ttk.Label(parent, textvariable=variable, style="Panel.TLabel", width=5, anchor="e")
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Scale(parent, from_=from_, to=to, variable=variable, orient="horizontal").grid(
            row=row, column=1, sticky="ew", padx=8, pady=4
        )
        value.grid(row=row, column=2, sticky="e", pady=4)

    def browse_output(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.output_dir.get() or str(Path.cwd()))
        if folder:
            self.output_dir.set(folder)

    def refresh_voices(self) -> None:
        try:
            self.voices = self.tts.list_voices()
        except Exception as error:  # pragma: no cover - UI boundary
            self.voices = []
            self._append_log(f"Could not load voices: {error}")

        names = [voice.name for voice in self.voices]
        self.voice_combo.configure(values=names)
        if names and not self.voice_name.get():
            self.voice_name.set(names[0])

    def start_generate(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        text = self.script_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Missing script", "Paste a script before generating.")
            return

        options = GenerationOptions(
            text=text,
            output_dir=Path(self.output_dir.get()).expanduser(),
            project_name=self.project_name.get(),
            voice_name=self.voice_name.get() or None,
            rate=self.rate.get(),
            volume=self.volume.get(),
            pause_ms=self.pause_ms.get(),
            max_chars=self.max_chars.get(),
            export_mp3=self.export_mp3.get(),
            keep_segments=self.keep_segments.get(),
        )

        self.last_result = None
        self.open_button.configure(state="disabled")
        self.generate_button.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Generating")
        self._append_log("Starting generation...")

        self.worker = threading.Thread(target=self._run_generation, args=(options,), daemon=True)
        self.worker.start()

    def _run_generation(self, options: GenerationOptions) -> None:
        try:
            result = generate_package(options, tts=self.tts, progress=lambda message: self.events.put(("log", message)))
            self.events.put(("done", result))
        except Exception as error:  # pragma: no cover - UI boundary
            self.events.put(("error", error))

    def _poll_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                self._append_log(str(payload))
            elif event == "done":
                self._finish_success(payload)
            elif event == "error":
                self._finish_error(payload)

        self.root.after(120, self._poll_events)

    def _finish_success(self, result: object) -> None:
        self.progress.stop()
        self.generate_button.configure(state="normal")
        self.open_button.configure(state="normal")
        self.status.set("Done")
        self.last_result = result if isinstance(result, GenerationResult) else None

        if self.last_result:
            self._append_log(f"WAV: {self.last_result.wav_path}")
            self._append_log(f"SRT: {self.last_result.srt_path}")
            if self.last_result.mp3_path:
                self._append_log(f"MP3: {self.last_result.mp3_path}")
            for warning in self.last_result.warnings:
                self._append_log(f"Warning: {warning}")

    def _finish_error(self, error: object) -> None:
        self.progress.stop()
        self.generate_button.configure(state="normal")
        self.status.set("Error")
        self._append_log(f"Error: {error}")
        messagebox.showerror("Generation failed", str(error))

    def open_output(self) -> None:
        if not self.last_result:
            return
        os.startfile(self.last_result.project_dir)  # type: ignore[attr-defined]

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


def run_app() -> None:
    root = tk.Tk()
    GalaxyStudioApp(root)
    root.mainloop()
