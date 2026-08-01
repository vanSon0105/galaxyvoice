from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config import AppConfig, default_config_path, load_app_config, save_app_config
from .engine import GenerationOptions, GenerationResult, generate_package
from .languages import code_from_label, label_from_code, language_labels
from .media import MediaExtractionOptions, MediaExtractionResult, extract_audio_from_video
from .transcription import (
    WHISPER_MODELS,
    VideoSubtitleDraft,
    VideoSubtitleOptions,
    VideoSubtitleResult,
    export_subtitle_package,
    prepare_subtitles_from_video,
)
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
from .tts import (
    EdgeTTS,
    TTSEngine,
    Voice,
    create_tts_engine,
    tts_engine_code,
    tts_engine_labels,
)


class GalaxyStudioApp:
    def __init__(self, root: tk.Tk, config_path: Path | None = None) -> None:
        self.root = root
        self.root.title("Galaxy AI Voice & Subtitle Studio")
        self.root.geometry("1120x720")
        self.root.minsize(900, 600)

        self.config_path = config_path or default_config_path()
        self._config_load_error: OSError | None = None
        try:
            saved_config = load_app_config(self.config_path)
        except OSError as error:
            saved_config = AppConfig()
            self._config_load_error = error
        self.tts: TTSEngine = create_tts_engine(saved_config.tts_engine)
        self.voices: list[Voice] = []
        self.worker: threading.Thread | None = None
        self.voice_worker: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.last_result: GenerationResult | MediaExtractionResult | VideoSubtitleResult | None = None
        self.subtitle_draft: VideoSubtitleDraft | None = None
        self._poll_after_id: str | None = None
        self._voice_refresh_after_id: str | None = None
        self._config_save_after_id: str | None = None
        self._config_save_enabled = False
        self._closing = False
        self._export_in_progress = False
        self._subtitle_draft_lock = threading.Lock()
        self._pending_subtitle_draft: VideoSubtitleDraft | None = None

        self.project_name = tk.StringVar(value="galaxy_project")
        self.output_dir = tk.StringVar(value=saved_config.output_dir or str(Path.cwd() / "exports"))
        self.video_path = tk.StringVar()
        self.tts_engine_name = tk.StringVar(value=self.tts.label)
        self.voice_name = tk.StringVar(value=saved_config.voice_name)
        self.rate = tk.IntVar(value=saved_config.rate)
        self.volume = tk.IntVar(value=saved_config.volume)
        self.pause_ms = tk.IntVar(value=saved_config.pause_ms)
        self.max_chars = tk.IntVar(value=saved_config.max_chars)
        self.export_mp3 = tk.BooleanVar(value=saved_config.export_mp3)
        self.keep_segments = tk.BooleanVar(value=saved_config.keep_segments)
        self.video_export_wav = tk.BooleanVar(value=saved_config.video_export_wav)
        self.video_export_mp3 = tk.BooleanVar(value=saved_config.video_export_mp3)
        self.video_source_language = tk.StringVar(
            value=label_from_code(saved_config.video_source_language, default=label_from_code("auto"))
        )
        self.video_target_language = tk.StringVar(
            value=label_from_code(saved_config.video_target_language, default=label_from_code("vi"))
        )
        self.whisper_model = tk.StringVar(value=saved_config.whisper_model)
        provider = saved_config.ai_provider or default_translation_provider()
        self.ai_provider = tk.StringVar(value=translation_provider_label(provider))
        self.ai_model = tk.StringVar(value=saved_config.ai_model or default_translation_model(provider))
        self.ai_base_url = tk.StringVar(value=saved_config.ai_base_url or default_translation_base_url(provider))
        self.ai_api_key = tk.StringVar(value=default_translation_api_key(provider))
        self.script_language_code = ""
        self._setting_script_text = False
        self.status = tk.StringVar(value="Ready")

        self._configure_style()
        self._build_layout()
        if self._config_load_error is not None:
            self._append_log(
                "Could not read config; automatic config saving is disabled for this session: "
                f"{self._config_load_error}"
            )
        self.root.bind("<Destroy>", self._on_destroy, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self._close_app)
        self._poll_events()
        initial_voices = self.tts.initial_voices()
        saved_voice_needs_refresh = bool(
            saved_config.voice_name
            and all(voice.name != saved_config.voice_name for voice in initial_voices)
        )
        self._apply_voices(initial_voices, preserve_current=True)
        if not initial_voices or saved_voice_needs_refresh:
            self._voice_refresh_after_id = self.root.after_idle(self._refresh_initial_voices)
        self._bind_config_traces()
        self._config_save_enabled = self._config_load_error is None

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
        left.rowconfigure(0, weight=1)
        self.subtitle_notebook = ttk.Notebook(left)
        self.subtitle_notebook.grid(row=0, column=0, sticky="nsew")
        self.script_tab, self.script_text = self._build_text_tab(
            self.subtitle_notebook,
            "Script",
            wrap="word",
            font=("Segoe UI", 11),
        )
        self.source_subtitle_tab, self.source_subtitle_text = self._build_text_tab(
            self.subtitle_notebook,
            "Sub gốc",
            wrap="word",
            font=("Consolas", 10),
        )
        self.translated_subtitle_tab, self.translated_subtitle_text = self._build_text_tab(
            self.subtitle_notebook,
            "Sub dịch",
            wrap="word",
            font=("Consolas", 10),
        )
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

    def _build_text_tab(
        self,
        notebook: ttk.Notebook,
        label: str,
        wrap: str,
        font: tuple[str, int],
    ) -> tuple[ttk.Frame, tk.Text]:
        tab = ttk.Frame(notebook, padding=1)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        editor = tk.Text(
            tab,
            wrap=wrap,
            undo=True,
            font=font,
            padx=14,
            pady=12,
            bg="#fffdfa",
            fg="#1f1f1f",
            insertbackground="#1f1f1f",
            relief="solid",
            bd=1,
        )
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=editor.yview)
        editor.configure(yscrollcommand=scrollbar.set)
        editor.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        notebook.add(tab, text=label)
        return tab, editor

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
        ttk.Label(parent, text="Engine", style="Panel.TLabel").grid(row=6, column=0, sticky="w", pady=(0, 2))
        self.tts_engine_combo = ttk.Combobox(
            parent,
            textvariable=self.tts_engine_name,
            values=tts_engine_labels(),
            state="readonly",
        )
        self.tts_engine_combo.grid(row=7, column=0, sticky="ew")
        self.tts_engine_combo.bind("<<ComboboxSelected>>", self._on_tts_engine_changed)

        ttk.Label(parent, text="Voice", style="Panel.TLabel").grid(row=8, column=0, sticky="w", pady=(10, 2))
        voice_row = ttk.Frame(parent, style="Surface.TFrame")
        voice_row.grid(row=9, column=0, sticky="ew")
        voice_row.columnconfigure(0, weight=1)
        self.voice_combo = ttk.Combobox(voice_row, textvariable=self.voice_name, state="readonly")
        self.voice_combo.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.refresh_voices_button = ttk.Button(voice_row, text="Refresh", command=self.refresh_voices)
        self.refresh_voices_button.grid(row=0, column=1)

        sliders = ttk.Frame(parent, style="Surface.TFrame")
        sliders.grid(row=10, column=0, sticky="ew", pady=(10, 0))
        sliders.columnconfigure(1, weight=1)
        self._add_slider(sliders, row=0, label="Speed", variable=self.rate, from_=-10, to=10)
        self._add_slider(sliders, row=1, label="Volume", variable=self.volume, from_=0, to=100)
        self._add_slider(sliders, row=2, label="Pause", variable=self.pause_ms, from_=0, to=1200)

    def _build_export_panel(self, parent: ttk.Frame) -> None:
        export = ttk.Frame(parent, style="Surface.TFrame")
        export.grid(row=11, column=0, sticky="ew", pady=(18, 0))
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
        video.grid(row=12, column=0, sticky="ew", pady=(18, 0))
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
            values=WHISPER_MODELS,
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
        self.subtitle_export_button = ttk.Button(
            button_row,
            text="Export Subtitles",
            command=self.start_export_subtitles,
            state="disabled",
        )
        self.subtitle_export_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

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
        if self.voice_worker and self.voice_worker.is_alive():
            return

        engine = self.tts
        self.refresh_voices_button.configure(state="disabled")
        self.tts_engine_combo.configure(state="disabled")
        self.voice_combo.configure(state="disabled")
        self._append_log(f"Loading {engine.label} voices...")
        self.voice_worker = threading.Thread(target=self._run_voice_refresh, args=(engine,), daemon=True)
        self.voice_worker.start()

    def _refresh_initial_voices(self) -> None:
        self._voice_refresh_after_id = None
        self.refresh_voices()

    def _run_voice_refresh(self, engine: TTSEngine) -> None:
        try:
            voices = engine.list_voices()
            self.events.put(("voices_loaded", (engine.code, voices)))
        except Exception as error:  # pragma: no cover - UI boundary
            self.events.put(("voices_error", (engine.code, error)))

    def _apply_voices(self, voices: list[Voice], preserve_current: bool = False) -> None:
        current_name = self.voice_name.get()
        if preserve_current and current_name and all(voice.name != current_name for voice in voices):
            voices = [Voice(name=current_name, culture="", gender="", age=""), *voices]
        self.voices = voices
        names = [voice.name for voice in self.voices]
        self.voice_combo.configure(values=names)
        if not names:
            return
        elif self.voice_name.get() not in names:
            preferred = self.tts.preferred_voice_name("vi")
            default_voice = preferred if preferred in names else names[0]
            self.voice_name.set(default_voice)

    def _on_tts_engine_changed(self, _event: tk.Event | None = None) -> None:
        self.tts = create_tts_engine(tts_engine_code(self.tts_engine_name.get()))
        self.voice_name.set("")
        initial_voices = self.tts.initial_voices()
        self._apply_voices(initial_voices)
        self._append_log(f"Voice engine: {self.tts.label}")
        if not initial_voices:
            self.refresh_voices()

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

        self.worker = threading.Thread(
            target=self._run_generation,
            args=(options, translation_options, self.tts),
            daemon=True,
        )
        self.worker.start()

    def _run_generation(
        self,
        options: GenerationOptions,
        translation_options: AITranslationOptions | None,
        tts_engine: TTSEngine | None = None,
    ) -> None:
        try:
            if translation_options:
                target = label_from_code(translation_options.target_language, default=translation_options.target_language)
                self.events.put(("log", f"Translating Script to {target}..."))
                translated_text = translate_script_text(options.text, translation_options)
                options = replace(options, text=translated_text)
                self.events.put(("script_translated", (translated_text, translation_options.target_language)))

            result = generate_package(
                options,
                tts=tts_engine or self.tts,
                progress=lambda message: self.events.put(("log", message)),
            )
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
            draft = prepare_subtitles_from_video(
                options,
                progress=lambda message: self.events.put(("log", message)),
            )
            with self._subtitle_draft_lock:
                if self._closing:
                    should_cleanup = True
                else:
                    self._pending_subtitle_draft = draft
                    self.events.put(("done", draft))
                    should_cleanup = False
            if should_cleanup:
                draft.cleanup()
        except Exception as error:  # pragma: no cover - UI boundary
            self.events.put(("error", error))

    def start_export_subtitles(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if self.subtitle_draft is None:
            messagebox.showwarning("Missing subtitles", "Create subtitles before exporting.")
            return

        source_srt_text = self.source_subtitle_text.get("1.0", "end-1c")
        translated_srt_text = (
            self.translated_subtitle_text.get("1.0", "end-1c")
            if self.subtitle_draft.translated_cues is not None
            else None
        )
        output_dir = Path(self.output_dir.get()).expanduser()
        project_name = self.project_name.get()

        self.last_result = None
        self.open_button.configure(state="disabled")
        self._set_busy(True)
        self.progress.start(12)
        self.status.set("Exporting")
        self._append_log("Exporting subtitle files...")

        self.worker = threading.Thread(
            target=self._run_subtitle_export,
            args=(
                self.subtitle_draft,
                output_dir,
                project_name,
                source_srt_text,
                translated_srt_text,
            ),
            daemon=False,
        )
        self._export_in_progress = True
        self.worker.start()

    def _run_subtitle_export(
        self,
        draft: VideoSubtitleDraft,
        output_dir: Path,
        project_name: str,
        source_srt_text: str,
        translated_srt_text: str | None,
    ) -> None:
        try:
            result = export_subtitle_package(
                draft,
                output_dir,
                project_name,
                source_srt_text=source_srt_text,
                translated_srt_text=translated_srt_text,
                progress=lambda message: self.events.put(("log", message)),
            )
            self.events.put(("done", result))
        except Exception as error:  # pragma: no cover - UI boundary
            self.events.put(("error", error))
        finally:
            self._export_in_progress = False
            if self._closing:
                draft.cleanup()

    def _on_ai_provider_changed(self, _event: tk.Event | None = None) -> None:
        provider = translation_provider_code(self.ai_provider.get())
        self.ai_model.set(default_translation_model(provider))
        self.ai_base_url.set(default_translation_base_url(provider))
        self.ai_api_key.set(default_translation_api_key(provider))

    def _bind_config_traces(self) -> None:
        variables: tuple[tk.Variable, ...] = (
            self.output_dir,
            self.tts_engine_name,
            self.voice_name,
            self.rate,
            self.volume,
            self.pause_ms,
            self.max_chars,
            self.export_mp3,
            self.keep_segments,
            self.video_export_wav,
            self.video_export_mp3,
            self.video_source_language,
            self.video_target_language,
            self.whisper_model,
            self.ai_provider,
            self.ai_model,
            self.ai_base_url,
        )
        for variable in variables:
            variable.trace_add("write", self._schedule_config_save)

    def _schedule_config_save(self, *_args: str) -> None:
        if not self._config_save_enabled:
            return
        if self._config_save_after_id:
            try:
                self.root.after_cancel(self._config_save_after_id)
            except tk.TclError:
                pass
        try:
            self._config_save_after_id = self.root.after(300, self._save_config_now)
        except tk.TclError:
            self._config_save_after_id = None

    def _save_config_now(self) -> None:
        if self._config_save_after_id:
            try:
                self.root.after_cancel(self._config_save_after_id)
            except tk.TclError:
                pass
            self._config_save_after_id = None

        if self._config_load_error is not None:
            return

        config = AppConfig(
            output_dir=self.output_dir.get().strip(),
            tts_engine=tts_engine_code(self.tts_engine_name.get()),
            voice_name=self.voice_name.get().strip(),
            rate=self._config_int(self.rate, 0, -10, 10),
            volume=self._config_int(self.volume, 100, 0, 100),
            pause_ms=self._config_int(self.pause_ms, 250, 0, 1200),
            max_chars=self._config_int(self.max_chars, 160, 60, 260),
            export_mp3=bool(self.export_mp3.get()),
            keep_segments=bool(self.keep_segments.get()),
            video_export_wav=bool(self.video_export_wav.get()),
            video_export_mp3=bool(self.video_export_mp3.get()),
            video_source_language=code_from_label(self.video_source_language.get(), default="auto"),
            video_target_language=code_from_label(self.video_target_language.get(), default="vi"),
            whisper_model=self.whisper_model.get().strip(),
            ai_provider=translation_provider_code(self.ai_provider.get()),
            ai_model=self.ai_model.get().strip(),
            ai_base_url=self.ai_base_url.get().strip(),
        )
        try:
            save_app_config(config, self.config_path)
        except OSError as error:
            self._append_log(f"Could not save config: {error}")

    @staticmethod
    def _config_int(variable: tk.IntVar, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(variable.get())
        except (tk.TclError, TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

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
            elif event == "voices_loaded":
                engine_code, voices = payload if isinstance(payload, tuple) else ("", [])
                if engine_code == self.tts.code and isinstance(voices, list):
                    self._apply_voices(voices)
                    self._append_log(f"Loaded {len(voices)} {self.tts.label} voices.")
                self._finish_voice_refresh()
            elif event == "voices_error":
                engine_code, error = payload if isinstance(payload, tuple) else ("", payload)
                if engine_code == self.tts.code:
                    self._append_log(f"Could not load {self.tts.label} voices: {error}")
                self._finish_voice_refresh()
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
        self.status.set("Done")
        self.last_result = result if isinstance(result, (GenerationResult, MediaExtractionResult, VideoSubtitleResult)) else None

        if isinstance(result, VideoSubtitleDraft):
            with self._subtitle_draft_lock:
                if self._pending_subtitle_draft is result:
                    self._pending_subtitle_draft = None
            self._replace_subtitle_draft(result)
            self._load_subtitle_draft(result)
            self.subtitle_export_button.configure(state="normal")
            self.open_button.configure(state="disabled")
            self.status.set("Ready to export")
            self._append_log(
                f"Created {result.cue_count} subtitle cues. Review Sub gốc/Sub dịch, then export when ready."
            )
            for warning in result.warnings:
                self._append_log(f"Warning: {warning}")
        elif isinstance(self.last_result, GenerationResult):
            self.open_button.configure(state="normal")
            self._append_log(f"WAV: {self.last_result.wav_path}")
            self._append_log(f"SRT: {self.last_result.srt_path}")
            if self.last_result.mp3_path:
                self._append_log(f"MP3: {self.last_result.mp3_path}")
            for warning in self.last_result.warnings:
                self._append_log(f"Warning: {warning}")
        elif isinstance(self.last_result, MediaExtractionResult):
            self.open_button.configure(state="normal")
            if self.last_result.wav_path:
                self._append_log(f"WAV: {self.last_result.wav_path}")
            if self.last_result.mp3_path:
                self._append_log(f"MP3: {self.last_result.mp3_path}")
            self._append_log(f"Manifest: {self.last_result.manifest_path}")
            for warning in self.last_result.warnings:
                self._append_log(f"Warning: {warning}")
        elif isinstance(self.last_result, VideoSubtitleResult):
            self.open_button.configure(state="normal")
            self._append_log(f"Audio: {self.last_result.audio_path}")
            self._append_log(f"Original SRT: {self.last_result.source_srt_path}")
            if self.last_result.translated_srt_path:
                self._append_log(f"Translated SRT: {self.last_result.translated_srt_path}")
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

    def _load_subtitle_script(self, result: VideoSubtitleDraft | VideoSubtitleResult) -> None:
        if not result.script_text.strip():
            return

        self._set_script_text(result.script_text)
        self.script_language_code = result.script_language

        language = label_from_code(result.script_language, default=result.script_language)
        self._append_log(f"Loaded {language} script into Script.")
        if self._select_voice_for_language(result.script_language):
            self._append_log(f"Selected voice for {language}: {self.voice_name.get()}")
        elif result.script_language not in {"auto", "none"}:
            self._append_log(f"No {self.tts.label} voice found for {language}; choose a matching voice before Generate.")

    def _load_subtitle_draft(self, draft: VideoSubtitleDraft) -> None:
        self._set_editor_text(self.source_subtitle_text, draft.source_srt_text)
        self._set_editor_text(self.translated_subtitle_text, draft.translated_srt_text)
        self._load_subtitle_script(draft)
        selected_tab = self.translated_subtitle_tab if draft.translated_cues is not None else self.source_subtitle_tab
        self.subtitle_notebook.select(selected_tab)

    def _replace_subtitle_draft(self, draft: VideoSubtitleDraft) -> None:
        if self.subtitle_draft is not None and self.subtitle_draft is not draft:
            self.subtitle_draft.cleanup()
        self.subtitle_draft = draft

    def _select_voice_for_language(self, language_code: str) -> bool:
        normalized = language_code.strip().lower()
        if not normalized or normalized in {"auto", "none"}:
            return False

        culture_prefix = f"{normalized}-"
        matching = [
            voice
            for voice in self.voices
            if voice.culture.strip().lower() == normalized
            or voice.culture.strip().lower().startswith(culture_prefix)
        ]
        if not matching:
            return False

        current_name = self.voice_name.get()
        if any(voice.name == current_name for voice in matching):
            return True

        preferred = self.tts.preferred_voice_name(normalized)
        if preferred and any(voice.name == preferred for voice in matching):
            self.voice_name.set(preferred)
            return True

        for voice in matching:
            self.voice_name.set(voice.name)
            return True
        return False

    def _set_script_text(self, text: str) -> None:
        self._setting_script_text = True
        try:
            self._set_editor_text(self.script_text, text)
        finally:
            self._setting_script_text = False

    @staticmethod
    def _set_editor_text(editor: tk.Text, text: str) -> None:
        editor.edit_separator()
        editor.delete("1.0", "end")
        editor.insert("1.0", text)
        editor.edit_separator()
        editor.edit_modified(False)

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
        export_state = "normal" if not busy and self.subtitle_draft is not None else "disabled"
        self.subtitle_export_button.configure(state=export_state)
        voice_refreshing = bool(self.voice_worker and self.voice_worker.is_alive())
        self.refresh_voices_button.configure(state="disabled" if busy or voice_refreshing else "normal")
        self.tts_engine_combo.configure(state="disabled" if busy else "readonly")
        self.voice_combo.configure(state="disabled" if busy else "readonly")

    def _finish_voice_refresh(self) -> None:
        self.voice_worker = None
        busy = bool(self.worker and self.worker.is_alive())
        self.refresh_voices_button.configure(state="disabled" if busy else "normal")
        self.tts_engine_combo.configure(state="disabled" if busy else "readonly")
        self.voice_combo.configure(state="disabled" if busy else "readonly")

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

    def _close_app(self) -> None:
        self._save_config_now()
        self.root.destroy()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return

        with self._subtitle_draft_lock:
            self._closing = True
            pending_draft = self._pending_subtitle_draft
            self._pending_subtitle_draft = None
        if pending_draft is not None:
            pending_draft.cleanup()

        if self.subtitle_draft is not None:
            if not self._export_in_progress:
                self.subtitle_draft.cleanup()
            self.subtitle_draft = None

        if self._config_save_after_id:
            try:
                self.root.after_cancel(self._config_save_after_id)
            except tk.TclError:
                pass
            self._config_save_after_id = None

        if self._voice_refresh_after_id:
            try:
                self.root.after_cancel(self._voice_refresh_after_id)
            except tk.TclError:
                pass
            self._voice_refresh_after_id = None

        if self._poll_after_id:
            try:
                self.root.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
            self._poll_after_id = None


def run_app() -> None:
    root = tk.Tk()
    GalaxyStudioApp(root)
    root.mainloop()
