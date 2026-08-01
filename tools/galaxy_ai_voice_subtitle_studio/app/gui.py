from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .engine import GenerationOptions, GenerationResult, generate_package
from .languages import code_from_label, label_from_code, language_labels
from .media import MediaExtractionOptions, MediaExtractionResult, extract_audio_from_video
from .transcription import VideoSubtitleOptions, VideoSubtitleResult, create_subtitles_from_video
from .translator import (
    AITranslationOptions,
    default_translation_api_key,
    default_translation_base_url,
    default_translation_model,
    default_translation_provider,
    translate_script_text,
    translation_provider_code,
    translation_provider_label,
    translation_provider_labels,
)
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
        self.last_result: GenerationResult | MediaExtractionResult | VideoSubtitleResult | None = None
        self._poll_after_id: str | None = None

        self.project_name = tk.StringVar(value="galaxy_project")
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "exports"))
        self.video_path = tk.StringVar()
        self.voice_name = tk.StringVar()
        self.rate = tk.IntVar(value=0)
        self.volume = tk.IntVar(value=100)
        self.pause_ms = tk.IntVar(value=250)
        self.max_chars = tk.IntVar(value=160)
        self.export_mp3 = tk.BooleanVar(value=True)
        self.keep_segments = tk.BooleanVar(value=True)
        self.video_export_wav = tk.BooleanVar(value=True)
        self.video_export_mp3 = tk.BooleanVar(value=True)
        self.video_source_language = tk.StringVar(value=label_from_code("auto"))
        self.video_target_language = tk.StringVar(value=label_from_code("vi"))
        self.whisper_model = tk.StringVar(value="base")
        provider = default_translation_provider()
        self.ai_provider = tk.StringVar(value=translation_provider_label(provider))
        self.ai_model = tk.StringVar(value=default_translation_model(provider))
        self.ai_base_url = tk.StringVar(value=default_translation_base_url(provider))
        self.ai_api_key = tk.StringVar(value=default_translation_api_key(provider))
        self.script_language_code = ""
        self._setting_script_text = False
        self.status = tk.StringVar(value="Ready")

        self._configure_style()
        self._build_layout()
        self.root.bind("<Destroy>", self._on_destroy, add="+")
        self._poll_events()
        self.refresh_voices()

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        self.root.configure(bg="#f4f1ea")
        style.configure(".", font=("Segoe UI", 10), background="#f4f1ea", foreground="#242424")
        style.configure("TFrame", background="#f4f1ea")
        style.configure("Panel.TFrame", background="#ffffff", borderwidth=1, relief="solid")
        style.configure("Surface.TFrame", background="#ffffff")
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
        self.script_text.bind("<<Modified>>", self._on_script_modified)

        right = ttk.Frame(shell, style="Panel.TFrame", padding=14)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        controls = self._build_scrollable_controls(right)
        self._build_project_panel(controls)
        self._build_voice_panel(controls)
        self._build_export_panel(controls)
        self._build_video_panel(controls)

        actions = ttk.Frame(right, style="Surface.TFrame")
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.generate_button = ttk.Button(actions, text="Generate", style="Accent.TButton", command=self.start_generate)
        self.generate_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.open_button = ttk.Button(actions, text="Open Output", command=self.open_output, state="disabled")
        self.open_button.grid(row=0, column=1, sticky="ew")

        self.progress = ttk.Progressbar(right, mode="indeterminate")
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))

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

    def _build_scrollable_controls(self, parent: ttk.Frame) -> ttk.Frame:
        canvas = tk.Canvas(parent, bg="#ffffff", highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        controls = ttk.Frame(canvas, style="Surface.TFrame")

        window_id = canvas.create_window((0, 0), window=controls, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        controls.columnconfigure(0, weight=1)
        controls.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.bind("<MouseWheel>", self._on_controls_mousewheel)
        controls.bind("<MouseWheel>", self._on_controls_mousewheel)
        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", self._on_controls_mousewheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
        controls.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", self._on_controls_mousewheel))
        controls.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
        return controls

    def _build_project_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Project", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(parent, text="Name", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 2))
        ttk.Entry(parent, textvariable=self.project_name).grid(row=2, column=0, sticky="ew")

        ttk.Label(parent, text="Output folder", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 2))
        output_row = ttk.Frame(parent, style="Surface.TFrame")
        output_row.grid(row=4, column=0, sticky="ew")
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.output_dir).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(output_row, text="Browse", command=self.browse_output).grid(row=0, column=1)

    def _build_voice_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Voice", style="Section.TLabel").grid(row=5, column=0, sticky="w", pady=(18, 8))
        voice_row = ttk.Frame(parent, style="Surface.TFrame")
        voice_row.grid(row=6, column=0, sticky="ew")
        voice_row.columnconfigure(0, weight=1)
        self.voice_combo = ttk.Combobox(voice_row, textvariable=self.voice_name, state="readonly")
        self.voice_combo.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(voice_row, text="Refresh", command=self.refresh_voices).grid(row=0, column=1)

        sliders = ttk.Frame(parent, style="Surface.TFrame")
        sliders.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        sliders.columnconfigure(1, weight=1)
        self._add_slider(sliders, row=0, label="Speed", variable=self.rate, from_=-10, to=10)
        self._add_slider(sliders, row=1, label="Volume", variable=self.volume, from_=0, to=100)
        self._add_slider(sliders, row=2, label="Pause", variable=self.pause_ms, from_=0, to=1200)

    def _build_export_panel(self, parent: ttk.Frame) -> None:
        export = ttk.Frame(parent, style="Surface.TFrame")
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

    def _build_video_panel(self, parent: ttk.Frame) -> None:
        video = ttk.Frame(parent, style="Surface.TFrame")
        video.grid(row=9, column=0, sticky="ew", pady=(18, 0))
        video.columnconfigure(0, weight=1)
        video.columnconfigure(1, weight=1)
        ttk.Label(video, text="Video", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")

        file_row = ttk.Frame(video, style="Surface.TFrame")
        file_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        file_row.columnconfigure(0, weight=1)
        ttk.Entry(file_row, textvariable=self.video_path).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(file_row, text="Browse", command=self.browse_video).grid(row=0, column=1)

        checks = ttk.Frame(video, style="Surface.TFrame")
        checks.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Checkbutton(checks, text="WAV", variable=self.video_export_wav).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(checks, text="MP3", variable=self.video_export_mp3).grid(row=0, column=1, sticky="w", padx=(12, 0))

        language_row = ttk.Frame(video, style="Surface.TFrame")
        language_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        language_row.columnconfigure(0, weight=1)
        language_row.columnconfigure(1, weight=1)
        ttk.Label(language_row, text="Video language", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(language_row, text="Translate to", style="Panel.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Combobox(
            language_row,
            textvariable=self.video_source_language,
            values=language_labels(include_auto=True),
            state="readonly",
        ).grid(row=1, column=0, sticky="ew", pady=(2, 0), padx=(0, 8))
        ttk.Combobox(
            language_row,
            textvariable=self.video_target_language,
            values=language_labels(include_auto=False, include_none=True),
            state="readonly",
        ).grid(row=1, column=1, sticky="ew", pady=(2, 0), padx=(8, 0))

        model_row = ttk.Frame(video, style="Surface.TFrame")
        model_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        model_row.columnconfigure(0, weight=1)
        model_row.columnconfigure(1, weight=1)
        ttk.Label(model_row, text="Whisper", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(model_row, text="AI provider", style="Panel.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Combobox(
            model_row,
            textvariable=self.whisper_model,
            values=["tiny", "base", "small", "medium", "large-v3"],
            state="readonly",
        ).grid(row=1, column=0, sticky="ew", pady=(2, 0), padx=(0, 8))
        self.ai_provider_combo = ttk.Combobox(
            model_row,
            textvariable=self.ai_provider,
            values=translation_provider_labels(),
            state="readonly",
        )
        self.ai_provider_combo.grid(row=1, column=1, sticky="ew", pady=(2, 0), padx=(8, 0))
        self.ai_provider_combo.bind("<<ComboboxSelected>>", self._on_ai_provider_changed)

        ttk.Label(video, text="AI model", style="Panel.TLabel").grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Entry(video, textvariable=self.ai_model).grid(row=6, column=0, columnspan=2, sticky="ew")
        ttk.Label(video, text="AI base URL", style="Panel.TLabel").grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Entry(video, textvariable=self.ai_base_url).grid(row=8, column=0, columnspan=2, sticky="ew")
        ttk.Label(video, text="AI API key", style="Panel.TLabel").grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Entry(video, textvariable=self.ai_api_key, show="*").grid(row=10, column=0, columnspan=2, sticky="ew")

        button_row = ttk.Frame(video, style="Surface.TFrame")
        button_row.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)
        self.extract_button = ttk.Button(button_row, text="Extract Audio", command=self.start_extract_video)
        self.extract_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.subtitle_button = ttk.Button(button_row, text="Create Subtitles", command=self.start_create_video_subtitles)
        self.subtitle_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))

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

    def browse_video(self) -> None:
        file_path = filedialog.askopenfilename(
            filetypes=[
                ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("All files", "*.*"),
            ]
        )
        if file_path:
            self.video_path.set(file_path)
            if self.project_name.get() == "galaxy_project":
                self.project_name.set(Path(file_path).stem)

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
        self._set_busy(True)
        self.progress.start(12)
        self.status.set("Generating")
        self._append_log("Starting generation...")

        translation_options = self._build_generation_translation_options()
        if translation_options:
            target = label_from_code(translation_options.target_language, default=translation_options.target_language)
            if self._select_voice_for_language(translation_options.target_language):
                options = replace(options, voice_name=self.voice_name.get() or None)
                self._append_log(f"Selected voice for {target}: {self.voice_name.get()}")
            self.status.set("Translating")
            self._append_log(f"Will translate Script to {target} before generating voice.")

        self.worker = threading.Thread(target=self._run_generation, args=(options, translation_options), daemon=True)
        self.worker.start()

    def _run_generation(self, options: GenerationOptions, translation_options: AITranslationOptions | None) -> None:
        try:
            if translation_options:
                target = label_from_code(translation_options.target_language, default=translation_options.target_language)
                self.events.put(("log", f"Translating Script to {target}..."))
                translated_text = translate_script_text(options.text, translation_options)
                options = replace(options, text=translated_text)
                self.events.put(("script_translated", (translated_text, translation_options.target_language)))

            result = generate_package(options, tts=self.tts, progress=lambda message: self.events.put(("log", message)))
            self.events.put(("done", result))
        except Exception as error:  # pragma: no cover - UI boundary
            self.events.put(("error", error))

    def start_extract_video(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        video = self.video_path.get().strip()
        if not video:
            messagebox.showwarning("Missing video", "Choose a video file before extracting audio.")
            return
        if not self.video_export_wav.get() and not self.video_export_mp3.get():
            messagebox.showwarning("Missing format", "Choose WAV, MP3, or both.")
            return

        options = MediaExtractionOptions(
            video_path=Path(video).expanduser(),
            output_dir=Path(self.output_dir.get()).expanduser(),
            project_name=self.project_name.get(),
            export_wav=self.video_export_wav.get(),
            export_mp3=self.video_export_mp3.get(),
        )

        self.last_result = None
        self.open_button.configure(state="disabled")
        self._set_busy(True)
        self.progress.start(12)
        self.status.set("Extracting")
        self._append_log("Starting video audio extraction...")

        self.worker = threading.Thread(target=self._run_video_extraction, args=(options,), daemon=True)
        self.worker.start()

    def _run_video_extraction(self, options: MediaExtractionOptions) -> None:
        try:
            result = extract_audio_from_video(options, progress=lambda message: self.events.put(("log", message)))
            self.events.put(("done", result))
        except Exception as error:  # pragma: no cover - UI boundary
            self.events.put(("error", error))

    def start_create_video_subtitles(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        video = self.video_path.get().strip()
        if not video:
            messagebox.showwarning("Missing video", "Choose a video file before creating subtitles.")
            return

        options = VideoSubtitleOptions(
            video_path=Path(video).expanduser(),
            output_dir=Path(self.output_dir.get()).expanduser(),
            project_name=self.project_name.get(),
            source_language=code_from_label(self.video_source_language.get(), default="auto"),
            target_language=code_from_label(self.video_target_language.get(), default="vi"),
            whisper_model=self.whisper_model.get(),
            ai_provider=translation_provider_code(self.ai_provider.get()),
            ai_model=self.ai_model.get(),
            ai_base_url=self.ai_base_url.get(),
            ai_api_key=self.ai_api_key.get(),
        )

        self.last_result = None
        self.open_button.configure(state="disabled")
        self._set_busy(True)
        self.progress.start(12)
        self.status.set("Subtitling")
        self._append_log("Starting video subtitle creation...")

        self.worker = threading.Thread(target=self._run_video_subtitles, args=(options,), daemon=True)
        self.worker.start()

    def _run_video_subtitles(self, options: VideoSubtitleOptions) -> None:
        try:
            result = create_subtitles_from_video(options, progress=lambda message: self.events.put(("log", message)))
            self.events.put(("done", result))
        except Exception as error:  # pragma: no cover - UI boundary
            self.events.put(("error", error))

    def _on_ai_provider_changed(self, _event: tk.Event | None = None) -> None:
        provider = translation_provider_code(self.ai_provider.get())
        self.ai_model.set(default_translation_model(provider))
        self.ai_base_url.set(default_translation_base_url(provider))
        self.ai_api_key.set(default_translation_api_key(provider))

    def _build_generation_translation_options(self) -> AITranslationOptions | None:
        source_language = self.script_language_code.strip().lower()
        target_language = code_from_label(self.video_target_language.get(), default="none")
        if not source_language or target_language == "none":
            return None
        if source_language != "auto" and source_language == target_language:
            return None

        provider = translation_provider_code(self.ai_provider.get())
        return AITranslationOptions(
            source_language=source_language,
            target_language=target_language,
            provider=provider,
            api_key=self.ai_api_key.get(),
            model=self.ai_model.get(),
            base_url=self.ai_base_url.get(),
        )

    def _poll_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                self._append_log(str(payload))
            elif event == "script_translated":
                text, language_code = payload if isinstance(payload, tuple) else ("", "")
                self._set_script_text(str(text))
                self.script_language_code = str(language_code)
                self._select_voice_for_language(self.script_language_code)
            elif event == "done":
                self._finish_success(payload)
            elif event == "error":
                self._finish_error(payload)

        try:
            self._poll_after_id = self.root.after(120, self._poll_events)
        except tk.TclError:
            self._poll_after_id = None

    def _finish_success(self, result: object) -> None:
        self.progress.stop()
        self._set_busy(False)
        self.open_button.configure(state="normal")
        self.status.set("Done")
        self.last_result = result if isinstance(result, (GenerationResult, MediaExtractionResult, VideoSubtitleResult)) else None

        if isinstance(self.last_result, GenerationResult):
            self._append_log(f"WAV: {self.last_result.wav_path}")
            self._append_log(f"SRT: {self.last_result.srt_path}")
            if self.last_result.mp3_path:
                self._append_log(f"MP3: {self.last_result.mp3_path}")
            for warning in self.last_result.warnings:
                self._append_log(f"Warning: {warning}")
        elif isinstance(self.last_result, MediaExtractionResult):
            if self.last_result.wav_path:
                self._append_log(f"WAV: {self.last_result.wav_path}")
            if self.last_result.mp3_path:
                self._append_log(f"MP3: {self.last_result.mp3_path}")
            self._append_log(f"Manifest: {self.last_result.manifest_path}")
            for warning in self.last_result.warnings:
                self._append_log(f"Warning: {warning}")
        elif isinstance(self.last_result, VideoSubtitleResult):
            self._append_log(f"Audio: {self.last_result.audio_path}")
            self._append_log(f"Original SRT: {self.last_result.source_srt_path}")
            if self.last_result.translated_srt_path:
                self._append_log(f"Translated SRT: {self.last_result.translated_srt_path}")
            self._load_subtitle_script(self.last_result)
            self._append_log(f"Manifest: {self.last_result.manifest_path}")
            for warning in self.last_result.warnings:
                self._append_log(f"Warning: {warning}")

    def _finish_error(self, error: object) -> None:
        self.progress.stop()
        self._set_busy(False)
        self.status.set("Error")
        self._append_log(f"Error: {error}")
        messagebox.showerror("Task failed", str(error))

    def open_output(self) -> None:
        if not self.last_result:
            return
        os.startfile(self.last_result.project_dir)  # type: ignore[attr-defined]

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _load_subtitle_script(self, result: VideoSubtitleResult) -> None:
        if not result.script_text.strip():
            return

        self._set_script_text(result.script_text)
        self.script_language_code = result.script_language

        language = label_from_code(result.script_language, default=result.script_language)
        self._append_log(f"Loaded {language} script into Script.")
        if self._select_voice_for_language(result.script_language):
            self._append_log(f"Selected voice for {language}: {self.voice_name.get()}")
        elif result.script_language not in {"auto", "none"}:
            self._append_log(f"No installed Windows voice found for {language}; Generate will use the selected voice.")

    def _select_voice_for_language(self, language_code: str) -> bool:
        normalized = language_code.strip().lower()
        if not normalized or normalized in {"auto", "none"}:
            return False

        culture_prefix = f"{normalized}-"
        for voice in self.voices:
            culture = voice.culture.strip().lower()
            if culture == normalized or culture.startswith(culture_prefix):
                self.voice_name.set(voice.name)
                return True

        return False

    def _set_script_text(self, text: str) -> None:
        self._setting_script_text = True
        try:
            self.script_text.edit_separator()
            self.script_text.delete("1.0", "end")
            self.script_text.insert("1.0", text)
            self.script_text.edit_separator()
            self.script_text.edit_modified(False)
        finally:
            self._setting_script_text = False

    def _on_script_modified(self, event: tk.Event) -> None:
        widget = event.widget
        if not isinstance(widget, tk.Text) or not widget.edit_modified():
            return
        if not self._setting_script_text:
            self.script_language_code = ""
        widget.edit_modified(False)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.generate_button.configure(state=state)
        self.extract_button.configure(state=state)
        self.subtitle_button.configure(state=state)

    def _on_controls_mousewheel(self, event: tk.Event) -> str:
        widget = event.widget
        canvas: tk.Canvas | None = None
        while widget:
            if isinstance(widget, tk.Canvas):
                canvas = widget
                break
            widget = widget.master

        if canvas is not None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self.root or not self._poll_after_id:
            return

        try:
            self.root.after_cancel(self._poll_after_id)
        except tk.TclError:
            pass
        self._poll_after_id = None


def run_app() -> None:
    root = tk.Tk()
    GalaxyStudioApp(root)
    root.mainloop()
