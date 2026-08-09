from __future__ import annotations

import os
import queue
import re
import subprocess
import tempfile
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import propainter
from .audio_separation import (
    AUDIO_OUTPUT_FORMATS,
    AUDIO_PROCESS_METHOD_LABELS,
    AUDIO_PROCESSING_DEVICE_LABELS,
    AUDIO_SAVED_SETTINGS,
    CPU_AUDIO_DEVICE,
    DEMUCS_METHOD,
    MDX_METHOD,
    VR_METHOD,
    AudioSeparationOptions,
    AudioSeparationResult,
    UVRModel,
    audio_device_code,
    audio_device_label,
    audio_method_code,
    audio_method_label,
    audio_separator_runtime_ready,
    default_audio_separator_runtime,
    default_uvr_root,
    discover_uvr_models,
    load_audio_presets,
    normalize_audio_method,
    resolve_audio_device,
    save_audio_presets,
    separate_audio,
)
from .compute import (
    PROCESSING_DEVICE_LABELS,
    processing_device_code,
    processing_device_label,
)
from .config import AppConfig, default_config_path, load_app_config, save_app_config
from .diagnostics import get_logger, log_operation_failure
from .engine import GenerationOptions, GenerationResult, generate_package
from .ffmpeg import find_ffmpeg, find_ffplay
from .languages import code_from_label, label_from_code, language_labels
from .media import MediaExtractionOptions, MediaExtractionResult, extract_audio_from_video
from .processes import managed_media_processes
from .subtitle_removal import (
    AI_INPAINT_MODES,
    AI_INPAINT_MODE,
    BLUR_MODE,
    FAST_AI_INPAINT_MODE,
    FILL_MODE,
    STRIP_MODE,
    SubtitleRemovalOptions,
    SubtitleRemovalResult,
    build_audio_playback_command,
    build_playback_command,
    create_video_preview,
    probe_video_duration,
    remove_subtitles_from_video,
)
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
    translation_provider_models,
)
from .tts import (
    EdgeTTS,
    TTSEngine,
    Voice,
    create_tts_engine,
    tts_engine_code,
    tts_engine_labels,
)


REMOVAL_MODE_LABELS = {
    STRIP_MODE: "Bỏ track phụ đề",
    BLUR_MODE: "Làm mờ vùng phụ đề",
    FILL_MODE: "Xóa thông minh",
    AI_INPAINT_MODE: "AI ProPainter",
    FAST_AI_INPAINT_MODE: "Fast AI (tối ưu)",
}
REMOVAL_MODE_CODES = {label: code for code, label in REMOVAL_MODE_LABELS.items()}
LOGGER = get_logger("gui")
PREVIEW_WIDTH = 480
PREVIEW_HEIGHT = 270
PREVIEW_FPS = 12


class GalaxyStudioApp:
    def __init__(self, root: tk.Tk, config_path: Path | None = None) -> None:
        managed_media_processes.reset()
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
        self.audio_presets_path = self.config_path.with_name("audio_presets.json")
        self.audio_custom_presets = load_audio_presets(self.audio_presets_path)
        self.tts: TTSEngine = create_tts_engine(saved_config.tts_engine)
        self.voices: list[Voice] = []
        self.worker: threading.Thread | None = None
        self.voice_worker: threading.Thread | None = None
        self._active_task: str | None = None
        self._audio_stop_event = threading.Event()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.last_result: (
            GenerationResult
            | MediaExtractionResult
            | VideoSubtitleResult
            | SubtitleRemovalResult
            | AudioSeparationResult
            | None
        ) = None
        self.subtitle_draft: VideoSubtitleDraft | None = None
        self._subtitle_draft_dirty = False
        self._subtitle_edit_revision = 0
        self._subtitle_export_revision: int | None = None
        self._poll_after_id: str | None = None
        self._voice_refresh_after_id: str | None = None
        self._config_save_after_id: str | None = None
        self._config_save_enabled = False
        self._closing = False
        self._export_in_progress = False
        self._subtitle_draft_lock = threading.Lock()
        self._pending_subtitle_draft: VideoSubtitleDraft | None = None
        self._preview_temp_dir = tempfile.TemporaryDirectory(prefix="galaxy_video_preview_")
        self._removal_drag_start: tuple[int, int] | None = None
        self._removal_preview_image: tk.PhotoImage | None = None
        self._playback_process: subprocess.Popen[bytes] | None = None
        self._playback_audio_process: subprocess.Popen[bytes] | None = None
        self._playback_worker: threading.Thread | None = None
        self._playback_stop = threading.Event()
        self._playback_frames: queue.Queue[tuple[int, bytes, float]] = queue.Queue(maxsize=2)
        self._playback_session = 0
        self._removal_preview_session = 0
        self._removal_preview_worker: threading.Thread | None = None
        self._timeline_dragging = False
        self._resume_after_timeline_seek = False
        self._ffplay_missing_logged = False

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
        self.voice_processing_device = tk.StringVar(
            value=processing_device_label(saved_config.voice_processing_device)
        )
        provider = saved_config.ai_provider or default_translation_provider()
        self.ai_provider = tk.StringVar(value=translation_provider_label(provider))
        self.ai_model = tk.StringVar(value=saved_config.ai_model or default_translation_model(provider))
        self.ai_base_url = tk.StringVar(value=saved_config.ai_base_url or default_translation_base_url(provider))
        self.ai_api_key = tk.StringVar(value=default_translation_api_key(provider))
        self.removal_video_path = tk.StringVar()
        self.removal_project_name = tk.StringVar()
        self.removal_mode = tk.StringVar(
            value=REMOVAL_MODE_LABELS.get(saved_config.subtitle_removal_mode, REMOVAL_MODE_LABELS[BLUR_MODE])
        )
        self.subtitle_region_x = tk.IntVar(value=saved_config.subtitle_region_x)
        self.subtitle_region_y = tk.IntVar(value=saved_config.subtitle_region_y)
        self.subtitle_region_width = tk.IntVar(value=saved_config.subtitle_region_width)
        self.subtitle_region_height = tk.IntVar(value=saved_config.subtitle_region_height)
        self.subtitle_blur_strength = tk.IntVar(value=saved_config.subtitle_blur_strength)
        self.removal_processing_device = tk.StringVar(
            value=processing_device_label(saved_config.removal_processing_device)
        )
        self.propainter_license_accepted = tk.BooleanVar(
            value=saved_config.propainter_license_accepted
        )
        self.audio_input_path = tk.StringVar()
        self.audio_output_dir = tk.StringVar(
            value=saved_config.audio_output_dir or saved_config.output_dir or str(Path.cwd() / "exports")
        )
        self.audio_format = tk.StringVar(value=saved_config.audio_output_format)
        self.audio_method = tk.StringVar(value=audio_method_label(saved_config.audio_process_method))
        self.audio_segment_size = tk.StringVar(value=saved_config.audio_segment_size)
        self.audio_overlap = tk.StringVar(value=saved_config.audio_overlap)
        self.audio_processing_device = tk.StringVar(
            value=audio_device_label(saved_config.audio_processing_device)
        )
        self.audio_gpu_conversion = tk.BooleanVar(value=saved_config.audio_gpu_conversion)
        self.audio_vocals_only = tk.BooleanVar(value=saved_config.audio_vocals_only)
        self.audio_instrumental_only = tk.BooleanVar(value=saved_config.audio_instrumental_only)
        self.audio_sample_mode = tk.BooleanVar(value=saved_config.audio_sample_mode)
        saved_audio_setting = saved_config.audio_saved_setting
        if (
            saved_audio_setting not in AUDIO_SAVED_SETTINGS
            and saved_audio_setting not in self.audio_custom_presets
        ):
            saved_audio_setting = "Default"
        self.audio_saved_setting = tk.StringVar(value=saved_audio_setting)
        self.audio_segment_label = tk.StringVar(value="Segment Size")
        self.audio_overlap_label = tk.StringVar(value="Overlap")
        self.audio_models = discover_uvr_models()
        saved_audio_model = next(
            (
                model
                for model in self.audio_models
                if model.method == normalize_audio_method(saved_config.audio_process_method)
                and model.filename == saved_config.audio_model_name
            ),
            None,
        )
        method_models = [
            model
            for model in self.audio_models
            if model.method == normalize_audio_method(saved_config.audio_process_method)
        ]
        initial_audio_model = saved_audio_model or (method_models[0] if method_models else None)
        self.audio_model = tk.StringVar(value=initial_audio_model.label if initial_audio_model else "")
        self.removal_timeline_position = tk.DoubleVar(value=0.0)
        self.removal_time_text = tk.StringVar(value="00:00 / 00:00")
        self.removal_duration_seconds = 0.0
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
        self._apply_voices(initial_voices, preserve_current=True)
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
        style.configure("PageSection.TLabel", font=("Segoe UI Semibold", 10), background="#f4f1ea")
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
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Galaxy AI Voice & Subtitle Studio", style="Header.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, textvariable=self.status).grid(row=0, column=1, sticky="e")

        self.main_notebook = ttk.Notebook(shell)
        self.main_notebook.grid(row=1, column=0, sticky="nsew")

        self.voice_tab = ttk.Frame(self.main_notebook, padding=(0, 10, 0, 0))
        self.voice_tab.columnconfigure(0, weight=1)
        self.voice_tab.columnconfigure(1, minsize=340)
        self.voice_tab.rowconfigure(0, weight=1)
        self.main_notebook.add(self.voice_tab, text="Voice")

        left = ttk.Frame(self.voice_tab)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
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
        self.source_subtitle_text.bind("<<Modified>>", self._on_subtitle_modified)
        self.translated_subtitle_text.bind("<<Modified>>", self._on_subtitle_modified)

        right = ttk.Frame(self.voice_tab, style="Panel.TFrame", padding=14)
        right.grid(row=0, column=1, sticky="nsew")
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

        self._build_audio_separation_tab()
        self._build_removal_tab()
        self.main_notebook.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)

        self.log_frame = ttk.Frame(shell)
        self.log_frame.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        self.log_frame.columnconfigure(0, weight=1)
        ttk.Label(self.log_frame, text="Log").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.log_text = tk.Text(
            self.log_frame,
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
            font=("Consolas", 9),
            bg="#202522",
            fg="#e9f1ec",
            relief="flat",
            padx=10,
            pady=8,
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

    def _build_removal_tab(self) -> None:
        self.removal_tab = ttk.Frame(self.main_notebook, padding=(0, 10, 0, 0))
        self.removal_tab.columnconfigure(0, weight=1)
        self.removal_tab.columnconfigure(1, minsize=340)
        self.removal_tab.rowconfigure(0, weight=1)
        self.main_notebook.add(self.removal_tab, text="Xóa phụ đề")

        preview_panel = ttk.Frame(self.removal_tab)
        preview_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(1, weight=1)
        ttk.Label(preview_panel, text="Xem trước", style="PageSection.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )

        preview_holder = ttk.Frame(preview_panel)
        preview_holder.grid(row=1, column=0, sticky="nsew")
        preview_holder.columnconfigure(0, weight=1)
        preview_holder.rowconfigure(0, weight=1)
        self.removal_preview_canvas = tk.Canvas(
            preview_holder,
            width=PREVIEW_WIDTH,
            height=PREVIEW_HEIGHT,
            bg="#161a18",
            highlightthickness=1,
            highlightbackground="#a8a59e",
            cursor="crosshair",
        )
        self.removal_preview_canvas.grid(row=0, column=0, sticky="n")
        self.removal_preview_canvas.create_text(
            PREVIEW_WIDTH // 2,
            PREVIEW_HEIGHT // 2,
            text="Chọn video để xem trước",
            fill="#d7ddd9",
            font=("Segoe UI", 11),
            tags=("preview-placeholder",),
        )
        self.removal_preview_canvas.bind("<ButtonPress-1>", self._start_removal_region_drag)
        self.removal_preview_canvas.bind("<B1-Motion>", self._drag_removal_region)
        self.removal_preview_canvas.bind("<ButtonRelease-1>", self._finish_removal_region_drag)
        self.removal_region_rectangle = self.removal_preview_canvas.create_rectangle(
            0,
            0,
            0,
            0,
            outline="#f1b847",
            width=3,
            fill="#f1b847",
            stipple="gray50",
        )
        self._draw_removal_region()

        transport = ttk.Frame(preview_panel)
        transport.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        transport.columnconfigure(1, weight=1)
        self.removal_play_button = ttk.Button(
            transport,
            text="Phát",
            command=self.toggle_removal_playback,
            state="disabled",
            width=10,
        )
        self.removal_play_button.grid(row=0, column=0, padx=(0, 8))
        self.removal_timeline = ttk.Scale(
            transport,
            from_=0,
            to=1,
            variable=self.removal_timeline_position,
            orient="horizontal",
            state="disabled",
            command=self._on_removal_timeline_changed,
        )
        self.removal_timeline.grid(row=0, column=1, sticky="ew")
        self.removal_timeline.bind("<ButtonPress-1>", self._start_removal_timeline_seek)
        self.removal_timeline.bind("<ButtonRelease-1>", self._finish_removal_timeline_seek)
        ttk.Label(
            transport,
            textvariable=self.removal_time_text,
            width=14,
            anchor="e",
        ).grid(row=0, column=2, padx=(8, 0))

        controls_panel = ttk.Frame(self.removal_tab, style="Panel.TFrame", padding=14)
        controls_panel.grid(row=0, column=1, sticky="nsew")
        controls_panel.configure(width=360)
        controls_panel.grid_propagate(False)
        controls_panel.columnconfigure(0, weight=1)
        controls_panel.rowconfigure(0, weight=1)
        controls = self._build_scrollable_controls(controls_panel)

        ttk.Label(controls, text="Video đầu vào", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        input_row = ttk.Frame(controls, style="Surface.TFrame")
        input_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        input_row.columnconfigure(0, weight=1)
        ttk.Entry(input_row, textvariable=self.removal_video_path).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(input_row, text="Browse", command=self.browse_removal_video).grid(row=0, column=1)

        ttk.Label(controls, text="Tên project", style="Panel.TLabel").grid(
            row=2, column=0, sticky="w", pady=(12, 2)
        )
        ttk.Entry(controls, textvariable=self.removal_project_name).grid(row=3, column=0, sticky="ew")

        ttk.Label(controls, text="Output folder", style="Panel.TLabel").grid(
            row=4, column=0, sticky="w", pady=(12, 2)
        )
        output_row = ttk.Frame(controls, style="Surface.TFrame")
        output_row.grid(row=5, column=0, sticky="ew")
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.output_dir).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(output_row, text="Browse", command=self.browse_output).grid(row=0, column=1)

        ttk.Label(controls, text="Chế độ", style="Panel.TLabel").grid(
            row=6, column=0, sticky="w", pady=(12, 2)
        )
        self.removal_mode_combo = ttk.Combobox(
            controls,
            textvariable=self.removal_mode,
            values=tuple(REMOVAL_MODE_LABELS.values()),
            state="readonly",
        )
        self.removal_mode_combo.grid(row=7, column=0, sticky="ew")
        self.removal_mode_combo.bind("<<ComboboxSelected>>", self._on_removal_mode_changed)

        device_row = ttk.Frame(controls, style="Surface.TFrame")
        device_row.grid(row=8, column=0, sticky="ew", pady=(12, 0))
        device_row.columnconfigure(0, weight=1)
        ttk.Label(device_row, text="Thiết bị xử lý", style="Panel.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 2)
        )
        self.removal_device_combo = ttk.Combobox(
            device_row,
            textvariable=self.removal_processing_device,
            values=tuple(PROCESSING_DEVICE_LABELS.values()),
            state="readonly",
        )
        self.removal_device_combo.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.propainter_install_button = ttk.Button(
            device_row,
            text="Cài ProPainter",
            command=self.install_propainter,
        )
        self.propainter_install_button.grid(row=1, column=1, sticky="e")

        region = ttk.Frame(controls, style="Surface.TFrame")
        region.grid(row=9, column=0, sticky="ew", pady=(14, 0))
        region.columnconfigure(1, weight=1)
        region.columnconfigure(3, weight=1)
        ttk.Label(region, text="Vùng phụ đề (%)", style="Section.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )
        self.removal_region_widgets: list[tk.Widget] = []
        region_fields = (
            ("X", self.subtitle_region_x, 0, 99),
            ("Y", self.subtitle_region_y, 0, 99),
            ("Rộng", self.subtitle_region_width, 1, 100),
            ("Cao", self.subtitle_region_height, 1, 100),
        )
        for index, (label, variable, minimum, maximum) in enumerate(region_fields):
            row = 1 + index // 2
            column = (index % 2) * 2
            ttk.Label(region, text=label, style="Panel.TLabel").grid(
                row=row, column=column, sticky="w", pady=3, padx=(0, 6)
            )
            spinbox = ttk.Spinbox(
                region,
                from_=minimum,
                to=maximum,
                increment=1,
                textvariable=variable,
                width=7,
            )
            spinbox.grid(row=row, column=column + 1, sticky="ew", pady=3, padx=(0, 10))
            self.removal_region_widgets.append(spinbox)

        blur_row = ttk.Frame(controls, style="Surface.TFrame")
        blur_row.grid(row=10, column=0, sticky="ew", pady=(12, 0))
        blur_row.columnconfigure(1, weight=1)
        ttk.Label(blur_row, text="Độ mờ", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        self.removal_blur_scale = ttk.Scale(
            blur_row,
            from_=1,
            to=50,
            variable=self.subtitle_blur_strength,
            orient="horizontal",
        )
        self.removal_blur_scale.grid(row=0, column=1, sticky="ew", padx=8)
        self.removal_region_widgets.append(self.removal_blur_scale)
        ttk.Label(
            blur_row,
            textvariable=self.subtitle_blur_strength,
            style="Panel.TLabel",
            width=4,
            anchor="e",
        ).grid(row=0, column=2, sticky="e")

        action_row = ttk.Frame(controls, style="Surface.TFrame")
        action_row.grid(row=11, column=0, sticky="ew", pady=(18, 0))
        action_row.columnconfigure(0, weight=1)
        action_row.columnconfigure(1, weight=1)
        self.removal_preview_button = ttk.Button(
            action_row,
            text="Xem trước",
            command=self.start_removal_preview,
        )
        self.removal_preview_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.removal_process_button = ttk.Button(
            action_row,
            text="Xử lý video",
            style="Accent.TButton",
            command=self.start_remove_subtitles,
        )
        self.removal_process_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.removal_open_button = ttk.Button(
            controls,
            text="Open Output",
            command=self.open_output,
            state="disabled",
        )
        self.removal_open_button.grid(row=12, column=0, sticky="ew", pady=(8, 0))
        self.removal_progress = ttk.Progressbar(controls, mode="indeterminate")
        self.removal_progress.grid(row=13, column=0, sticky="ew", pady=(12, 0))
        self._on_removal_mode_changed()

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

        ttk.Label(model_row, text="Thiết bị xử lý", style="Panel.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(10, 2)
        )
        self.voice_device_combo = ttk.Combobox(
            model_row,
            textvariable=self.voice_processing_device,
            values=tuple(PROCESSING_DEVICE_LABELS.values()),
            state="readonly",
        )
        self.voice_device_combo.grid(row=3, column=0, columnspan=2, sticky="ew")

        ttk.Label(video, text="AI model", style="Panel.TLabel").grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self.ai_model_combo = ttk.Combobox(
            video,
            textvariable=self.ai_model,
            values=translation_provider_models(translation_provider_code(self.ai_provider.get())),
        )
        self.ai_model_combo.grid(row=6, column=0, columnspan=2, sticky="ew")
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
        ttk.Label(body, text=str(uvr_root), wraplength=620).grid(
            row=1, column=0, sticky="w", pady=(4, 12)
        )
        ttk.Label(body, text=f"Models detected: {model_count}").grid(row=2, column=0, sticky="w")
        ttk.Label(body, text="Audio separator runtime", style="PageSection.TLabel").grid(
            row=3, column=0, sticky="w", pady=(14, 0)
        )
        ttk.Label(body, text=str(runtime.python_path), wraplength=620).grid(
            row=4, column=0, sticky="w", pady=(4, 4)
        )
        ttk.Label(
            body,
            text=runtime_status,
            foreground="#145c54" if ready else "#a33b24",
            wraplength=620,
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
        installer = Path(__file__).resolve().parents[1] / "install_audio_separator.ps1"
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
        if not file_path or file_path == self.video_path.get():
            return
        if not self._confirm_discard_subtitle_draft(
            "Đổi video sẽ bỏ bản phụ đề hiện tại chưa export. Tiếp tục?"
        ):
            return

        self._discard_subtitle_draft()
        self.video_path.set(file_path)
        if self.project_name.get() == "galaxy_project":
            self.project_name.set(Path(file_path).stem)

    def browse_removal_video(self) -> None:
        file_path = filedialog.askopenfilename(
            filetypes=[
                ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("All files", "*.*"),
            ]
        )
        if not file_path:
            return

        self._stop_removal_playback()
        self.removal_video_path.set(file_path)
        self.removal_project_name.set(f"{Path(file_path).stem}-clean")
        self.removal_duration_seconds = 0.0
        self.removal_timeline_position.set(0.0)
        self.removal_time_text.set("00:00 / 00:00")
        self.removal_play_button.configure(state="disabled")
        self.removal_timeline.configure(state="disabled", to=1)
        self.start_removal_preview()

    def _on_removal_mode_changed(self, _event: tk.Event | None = None) -> None:
        mode = self._removal_mode_code()
        region_state = "disabled" if mode == STRIP_MODE else "normal"
        for widget in self.removal_region_widgets[:-1]:
            widget.configure(state=region_state)
        self.removal_blur_scale.configure(state="normal" if mode == BLUR_MODE else "disabled")
        if hasattr(self, "propainter_install_button"):
            busy = bool(self.worker and self.worker.is_alive())
            ai_ready = mode in AI_INPAINT_MODES and not busy
            self.removal_device_combo.configure(state="readonly" if ai_ready else "disabled")
            install_state = "normal" if ai_ready else "disabled"
            self.propainter_install_button.configure(state=install_state)
        self._draw_removal_region()

    def _removal_mode_code(self) -> str:
        return REMOVAL_MODE_CODES.get(self.removal_mode.get(), BLUR_MODE)

    def _draw_removal_region(self, *_args: str) -> None:
        if not hasattr(self, "removal_preview_canvas"):
            return
        if self._removal_mode_code() == STRIP_MODE:
            self.removal_preview_canvas.itemconfigure(self.removal_region_rectangle, state="hidden")
            return

        x = self._config_int(self.subtitle_region_x, 5, 0, 99)
        y = self._config_int(self.subtitle_region_y, 75, 0, 99)
        width = min(self._config_int(self.subtitle_region_width, 90, 1, 100), 100 - x)
        height = min(self._config_int(self.subtitle_region_height, 20, 1, 100), 100 - y)
        self.removal_preview_canvas.coords(
            self.removal_region_rectangle,
            x * PREVIEW_WIDTH / 100,
            y * PREVIEW_HEIGHT / 100,
            (x + width) * PREVIEW_WIDTH / 100,
            (y + height) * PREVIEW_HEIGHT / 100,
        )
        self.removal_preview_canvas.itemconfigure(self.removal_region_rectangle, state="normal")
        self.removal_preview_canvas.tag_raise(self.removal_region_rectangle)

    def _start_removal_region_drag(self, event: tk.Event) -> None:
        if self._removal_mode_code() == STRIP_MODE:
            return
        self._removal_drag_start = (
            max(0, min(PREVIEW_WIDTH, int(event.x))),
            max(0, min(PREVIEW_HEIGHT, int(event.y))),
        )

    def _drag_removal_region(self, event: tk.Event) -> None:
        if self._removal_drag_start is None:
            return
        start_x, start_y = self._removal_drag_start
        current_x = max(0, min(PREVIEW_WIDTH, int(event.x)))
        current_y = max(0, min(PREVIEW_HEIGHT, int(event.y)))
        self.removal_preview_canvas.coords(
            self.removal_region_rectangle,
            min(start_x, current_x),
            min(start_y, current_y),
            max(start_x, current_x),
            max(start_y, current_y),
        )

    def _finish_removal_region_drag(self, event: tk.Event) -> None:
        if self._removal_drag_start is None:
            return
        start_x, start_y = self._removal_drag_start
        self._removal_drag_start = None
        end_x = max(0, min(PREVIEW_WIDTH, int(event.x)))
        end_y = max(0, min(PREVIEW_HEIGHT, int(event.y)))
        left, right = sorted((start_x, end_x))
        top, bottom = sorted((start_y, end_y))
        if right - left < 4 or bottom - top < 4:
            self._draw_removal_region()
            return

        region_x = min(99, round(left * 100 / PREVIEW_WIDTH))
        region_y = min(99, round(top * 100 / PREVIEW_HEIGHT))
        region_width = max(1, min(100 - region_x, round((right - left) * 100 / PREVIEW_WIDTH)))
        region_height = max(1, min(100 - region_y, round((bottom - top) * 100 / PREVIEW_HEIGHT)))
        self.subtitle_region_x.set(region_x)
        self.subtitle_region_y.set(region_y)
        self.subtitle_region_width.set(region_width)
        self.subtitle_region_height.set(region_height)
        self._draw_removal_region()

    def start_removal_preview(self, timestamp_seconds: float | None = None) -> None:
        if (
            self.worker
            and self.worker.is_alive()
            and self.worker is not self._removal_preview_worker
        ):
            return
        video = self.removal_video_path.get().strip()
        if not video:
            messagebox.showwarning("Missing video", "Choose a video before loading a preview.")
            return

        self._stop_removal_playback()
        self._removal_preview_session += 1
        session = self._removal_preview_session
        timestamp = max(0.0, float(timestamp_seconds or 0.0))
        preview_path = Path(self._preview_temp_dir.name) / f"preview-{session}.png"
        self._set_busy(True)
        self.removal_progress.start(12)
        self.status.set("Loading preview")
        self._append_log("Loading video preview...")
        preview_worker = threading.Thread(
            target=self._run_removal_preview,
            args=(session, Path(video).expanduser(), preview_path, timestamp),
            daemon=True,
        )
        self._removal_preview_worker = preview_worker
        self.worker = preview_worker
        preview_worker.start()

    def _run_removal_preview(
        self,
        session: int,
        video_path: Path,
        preview_path: Path,
        timestamp_seconds: float,
    ) -> None:
        try:
            duration = probe_video_duration(video_path)
            timestamp = min(timestamp_seconds, max(0.0, duration - 0.001))
            result = create_video_preview(
                video_path,
                preview_path,
                timestamp_seconds=timestamp,
            )
            self.events.put(
                (
                    "removal_preview_ready",
                    (session, str(video_path), result, duration, timestamp),
                )
            )
        except Exception as error:  # pragma: no cover - UI boundary
            self.events.put(("removal_preview_error", (session, str(video_path), error)))

    def _load_removal_preview(
        self,
        preview_path: Path,
        duration_seconds: float,
        position_seconds: float,
    ) -> None:
        self._removal_preview_image = tk.PhotoImage(file=str(preview_path))
        self._show_removal_preview_image(self._removal_preview_image)
        self.removal_duration_seconds = duration_seconds
        self.removal_timeline.configure(to=max(0.001, duration_seconds), state="normal")
        self.removal_play_button.configure(state="normal")
        self._set_removal_timeline_position(position_seconds)

    def _show_removal_preview_image(self, preview_image: tk.PhotoImage) -> None:
        self.removal_preview_canvas.delete("preview-image")
        self.removal_preview_canvas.delete("preview-placeholder")
        self.removal_preview_canvas.create_image(
            0,
            0,
            image=preview_image,
            anchor="nw",
            tags=("preview-image",),
        )
        self.removal_preview_canvas.tag_lower("preview-image")
        self._draw_removal_region()

    def toggle_removal_playback(self) -> None:
        if self._is_removal_playing():
            self._stop_removal_playback()
            return
        self._start_removal_playback()

    def _start_removal_playback(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        video = self.removal_video_path.get().strip()
        if not video:
            messagebox.showwarning("Missing video", "Choose a video before playing the preview.")
            return
        if self.removal_duration_seconds <= 0:
            self.start_removal_preview()
            return

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            messagebox.showerror("Playback unavailable", "ffmpeg was not found. Run install_ffmpeg.ps1 first.")
            return

        self._stop_removal_playback()
        start_seconds = max(0.0, float(self.removal_timeline_position.get()))
        if start_seconds >= self.removal_duration_seconds - 0.05:
            start_seconds = 0.0
            self._set_removal_timeline_position(0.0)

        session = self._playback_session
        stop_event = threading.Event()
        self._playback_stop = stop_event
        command = build_playback_command(
            ffmpeg,
            Path(video).expanduser(),
            start_seconds=start_seconds,
            width=PREVIEW_WIDTH,
            height=PREVIEW_HEIGHT,
            fps=PREVIEW_FPS,
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as error:
            messagebox.showerror("Playback unavailable", str(error))
            return

        self._playback_process = process
        self._start_removal_audio(Path(video).expanduser(), start_seconds, creationflags)
        self.removal_play_button.configure(text="Tạm dừng")
        self._playback_worker = threading.Thread(
            target=self._read_removal_playback_frames,
            args=(process, stop_event, session, start_seconds),
            daemon=True,
        )
        self._playback_worker.start()

    def _start_removal_audio(self, video_path: Path, start_seconds: float, creationflags: int) -> None:
        ffplay = find_ffplay()
        if not ffplay:
            if not self._ffplay_missing_logged:
                self._append_log("ffplay is not bundled yet; video preview will play without audio.")
                self._ffplay_missing_logged = True
            return
        try:
            self._playback_audio_process = subprocess.Popen(
                build_audio_playback_command(ffplay, video_path, start_seconds=start_seconds),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as error:
            self._append_log(f"Could not start preview audio: {error}")
            self._playback_audio_process = None

    def _read_removal_playback_frames(
        self,
        process: subprocess.Popen[bytes],
        stop_event: threading.Event,
        session: int,
        start_seconds: float,
    ) -> None:
        frame_size = PREVIEW_WIDTH * PREVIEW_HEIGHT * 3
        frame_index = 0
        stdout = process.stdout
        if stdout is None:
            return

        while not stop_event.is_set():
            frame = self._read_exact(stdout, frame_size)
            if len(frame) != frame_size:
                break
            position = min(
                self.removal_duration_seconds,
                start_seconds + frame_index / PREVIEW_FPS,
            )
            frame_index += 1
            self._offer_playback_frame((session, frame, position))

        if stop_event.is_set():
            return

        return_code = process.wait()
        final_position = min(
            self.removal_duration_seconds,
            start_seconds + frame_index / PREVIEW_FPS,
        )
        if return_code:
            stderr = process.stderr.read() if process.stderr is not None else b""
            detail = stderr.decode("utf-8", errors="replace").strip()
            message = detail or f"ffmpeg exited with code {return_code}."
            self.events.put(("removal_playback_error", (session, message)))
            return
        self.events.put(("removal_playback_ended", (session, final_position)))

    @staticmethod
    def _read_exact(stream: object, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = stream.read(remaining)  # type: ignore[attr-defined]
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _offer_playback_frame(self, frame: tuple[int, bytes, float]) -> None:
        try:
            self._playback_frames.put_nowait(frame)
        except queue.Full:
            try:
                self._playback_frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._playback_frames.put_nowait(frame)
            except queue.Full:
                pass

    def _render_latest_playback_frame(self) -> None:
        latest: tuple[int, bytes, float] | None = None
        while True:
            try:
                latest = self._playback_frames.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return

        session, frame, position = latest
        if session != self._playback_session:
            return
        ppm_header = f"P6\n{PREVIEW_WIDTH} {PREVIEW_HEIGHT}\n255\n".encode("ascii")
        self._removal_preview_image = tk.PhotoImage(data=ppm_header + frame, format="PPM")
        self._show_removal_preview_image(self._removal_preview_image)
        if not self._timeline_dragging:
            self._set_removal_timeline_position(position)

    def _stop_removal_playback(self, *, update_ui: bool = True) -> None:
        self._playback_session += 1
        self._playback_stop.set()
        processes = tuple(
            process
            for process in (self._playback_process, self._playback_audio_process)
            if process is not None
        )
        for process in processes:
            if process.poll() is not None:
                continue
            try:
                process.terminate()
            except OSError:
                pass
        self._playback_process = None
        self._playback_audio_process = None
        self._playback_worker = None
        if processes:
            threading.Thread(
                target=self._reap_playback_processes,
                args=(processes,),
                daemon=True,
            ).start()
        while True:
            try:
                self._playback_frames.get_nowait()
            except queue.Empty:
                break
        if update_ui:
            try:
                self.removal_play_button.configure(text="Phát")
            except tk.TclError:
                pass

    @staticmethod
    def _reap_playback_processes(processes: tuple[subprocess.Popen[bytes], ...]) -> None:
        for process in processes:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=0.5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            except OSError:
                pass

            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def _is_removal_playing(self) -> bool:
        return self._playback_process is not None and self._playback_process.poll() is None

    def _on_removal_timeline_changed(self, value: str) -> None:
        try:
            position = float(value)
        except ValueError:
            return
        self._update_removal_time_text(position)

    def _start_removal_timeline_seek(self, _event: tk.Event) -> None:
        self._timeline_dragging = True
        self._resume_after_timeline_seek = self._is_removal_playing()
        if self._resume_after_timeline_seek:
            self._stop_removal_playback()

    def _finish_removal_timeline_seek(self, _event: tk.Event) -> None:
        self._timeline_dragging = False
        position = max(
            0.0,
            min(self.removal_duration_seconds, float(self.removal_timeline_position.get())),
        )
        self._set_removal_timeline_position(position)
        if self._resume_after_timeline_seek:
            self._resume_after_timeline_seek = False
            self._start_removal_playback()
        else:
            self.start_removal_preview(position)

    def _set_removal_timeline_position(self, position_seconds: float) -> None:
        position = max(0.0, min(self.removal_duration_seconds, position_seconds))
        self.removal_timeline_position.set(position)
        self._update_removal_time_text(position)

    def _update_removal_time_text(self, position_seconds: float) -> None:
        self.removal_time_text.set(
            f"{self._format_playback_time(position_seconds)} / "
            f"{self._format_playback_time(self.removal_duration_seconds)}"
        )

    @staticmethod
    def _format_playback_time(seconds: float) -> str:
        total_seconds = max(0, int(seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours:02}:{minutes:02}:{secs:02}"
        return f"{minutes:02}:{secs:02}"

    def _on_main_tab_changed(self, _event: tk.Event | None = None) -> None:
        selected_tab = self.main_notebook.select()
        if selected_tab != str(self.removal_tab):
            self._stop_removal_playback()
        if selected_tab == str(self.audio_tab):
            self.log_frame.grid_remove()
        else:
            self.log_frame.grid()

    def _confirm_propainter_license(self) -> bool:
        if self.propainter_license_accepted.get():
            return True
        accepted = messagebox.askyesno(
            "Giấy phép ProPainter",
            "ProPainter chỉ được cấp phép cho mục đích phi thương mại theo NTU S-Lab License 1.0. "
            "Bạn xác nhận chỉ sử dụng chế độ này trong phạm vi giấy phép?",
        )
        if accepted:
            self.propainter_license_accepted.set(True)
        return accepted

    def install_propainter(self) -> None:
        if not self._confirm_propainter_license():
            return
        installer = Path(__file__).resolve().parents[1] / "install_propainter.ps1"
        if not installer.is_file():
            messagebox.showerror("Installer missing", f"Could not find: {installer}")
            return
        device = processing_device_code(self.removal_processing_device.get())
        command = [
            "powershell",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(installer),
            "-AcceptNonCommercialLicense",
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
        self._append_log("Opened the ProPainter installer in a separate window.")

    def start_remove_subtitles(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self._stop_removal_playback()
        video = self.removal_video_path.get().strip()
        if not video:
            messagebox.showwarning("Missing video", "Choose a video before processing.")
            return
        mode = self._removal_mode_code()
        if mode in AI_INPAINT_MODES:
            if not self._confirm_propainter_license():
                return
            try:
                propainter.resolve_propainter_runtime()
            except RuntimeError:
                install_now = messagebox.askyesno(
                    "ProPainter chưa được cài",
                    "Chế độ AI cần cài ProPainter trước khi xử lý video. "
                    "Mở bộ cài ProPainter ngay?\n\n"
                    "Sau khi cửa sổ cài đặt báo ProPainter is ready, hãy bấm Xử lý video lại.",
                )
                if install_now:
                    self.install_propainter()
                return

        region_x = self._config_int(self.subtitle_region_x, 5, 0, 99)
        region_y = self._config_int(self.subtitle_region_y, 75, 0, 99)
        region_width = min(
            self._config_int(self.subtitle_region_width, 90, 1, 100),
            100 - region_x,
        )
        region_height = min(
            self._config_int(self.subtitle_region_height, 20, 1, 100),
            100 - region_y,
        )
        options = SubtitleRemovalOptions(
            video_path=Path(video).expanduser(),
            output_dir=Path(self.output_dir.get()).expanduser(),
            project_name=self.removal_project_name.get(),
            mode=mode,
            region_x=region_x,
            region_y=region_y,
            region_width=region_width,
            region_height=region_height,
            blur_strength=self._config_int(self.subtitle_blur_strength, 18, 1, 100),
            processing_device=processing_device_code(self.removal_processing_device.get()),
        )

        self.last_result = None
        self.open_button.configure(state="disabled")
        self.removal_open_button.configure(state="disabled")
        self._set_busy(True)
        self.removal_progress.start(12)
        self.status.set("Removing subtitles")
        self._append_log("Starting subtitle removal...")
        self.worker = threading.Thread(
            target=self._run_subtitle_removal,
            args=(options,),
            daemon=True,
        )
        self.worker.start()

    def _run_subtitle_removal(self, options: SubtitleRemovalOptions) -> None:
        try:
            result = remove_subtitles_from_video(
                options,
                progress=lambda message: self.events.put(("log", message)),
            )
            self.events.put(("done", result))
        except Exception as error:  # pragma: no cover - UI boundary
            self.events.put(("error", error))

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

        translation_options = self._build_generation_translation_options()
        source_language = self._script_source_language()
        voice_language = (
            translation_options.target_language
            if translation_options is not None
            else source_language
        )
        if voice_language and voice_language not in {"auto", "none"}:
            voice_language_label = label_from_code(voice_language, default=voice_language)
            if not self._select_voice_for_language(voice_language):
                if not self.voice_worker or not self.voice_worker.is_alive():
                    self.refresh_voices()
                messagebox.showwarning(
                    "Missing matching voice",
                    f"Chưa tải được voice cho {voice_language_label}. "
                    "Đợi Refresh hoàn tất rồi bấm Generate lại.",
                )
                return
            options = replace(options, voice_name=self.voice_name.get() or None)

        self.last_result = None
        self.open_button.configure(state="disabled")
        self.removal_open_button.configure(state="disabled")
        self._set_busy(True)
        self.progress.start(12)
        self.status.set("Generating")
        self._append_log("Starting generation...")

        if translation_options:
            self._append_log(f"Selected voice for {voice_language_label}: {self.voice_name.get()}")
            self.status.set("Translating")
            self._append_log(
                f"Will translate Script to {voice_language_label} before generating voice."
            )

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
        self.removal_open_button.configure(state="disabled")
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
        if not self._confirm_discard_subtitle_draft(
            "Tạo lại phụ đề sẽ bỏ bản hiện tại chưa export. Tiếp tục?"
        ):
            return
        self._discard_subtitle_draft()

        options = VideoSubtitleOptions(
            video_path=Path(video).expanduser(),
            output_dir=Path(self.output_dir.get()).expanduser(),
            project_name=self.project_name.get(),
            source_language=code_from_label(self.video_source_language.get(), default="auto"),
            target_language=code_from_label(self.video_target_language.get(), default="vi"),
            whisper_model=self.whisper_model.get(),
            processing_device=processing_device_code(self.voice_processing_device.get()),
            ai_provider=translation_provider_code(self.ai_provider.get()),
            ai_model=self.ai_model.get(),
            ai_base_url=self.ai_base_url.get(),
            ai_api_key=self.ai_api_key.get(),
        )

        self.last_result = None
        self.open_button.configure(state="disabled")
        self.removal_open_button.configure(state="disabled")
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
                detailed_progress=lambda stage, completed, total: self.events.put(
                    ("task_progress", (stage, completed, total))
                ),
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
        selected_video = self.video_path.get().strip()
        if selected_video and not _same_path(Path(selected_video), self.subtitle_draft.source_video):
            messagebox.showwarning(
                "Video changed",
                "Bản phụ đề hiện tại thuộc video khác. Hãy tạo phụ đề cho video đang chọn trước khi export.",
            )
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
        self.removal_open_button.configure(state="disabled")
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
        self._subtitle_export_revision = self._subtitle_edit_revision
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
        self.ai_model_combo.configure(values=translation_provider_models(provider))

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
            self.voice_processing_device,
            self.ai_provider,
            self.ai_model,
            self.ai_base_url,
            self.removal_mode,
            self.subtitle_region_x,
            self.subtitle_region_y,
            self.subtitle_region_width,
            self.subtitle_region_height,
            self.subtitle_blur_strength,
            self.removal_processing_device,
            self.propainter_license_accepted,
            self.audio_output_dir,
            self.audio_format,
            self.audio_method,
            self.audio_model,
            self.audio_segment_size,
            self.audio_overlap,
            self.audio_processing_device,
            self.audio_gpu_conversion,
            self.audio_vocals_only,
            self.audio_instrumental_only,
            self.audio_sample_mode,
            self.audio_saved_setting,
        )
        for variable in variables:
            variable.trace_add("write", self._schedule_config_save)
        for variable in (
            self.subtitle_region_x,
            self.subtitle_region_y,
            self.subtitle_region_width,
            self.subtitle_region_height,
        ):
            variable.trace_add("write", self._draw_removal_region)

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

        region_x = self._config_int(self.subtitle_region_x, 5, 0, 99)
        region_y = self._config_int(self.subtitle_region_y, 75, 0, 99)
        selected_audio_model = self._selected_audio_model()
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
            voice_processing_device=processing_device_code(self.voice_processing_device.get()),
            ai_provider=translation_provider_code(self.ai_provider.get()),
            ai_model=self.ai_model.get().strip(),
            ai_base_url=self.ai_base_url.get().strip(),
            subtitle_removal_mode=self._removal_mode_code(),
            subtitle_region_x=region_x,
            subtitle_region_y=region_y,
            subtitle_region_width=min(
                self._config_int(self.subtitle_region_width, 90, 1, 100),
                100 - region_x,
            ),
            subtitle_region_height=min(
                self._config_int(self.subtitle_region_height, 20, 1, 100),
                100 - region_y,
            ),
            subtitle_blur_strength=self._config_int(self.subtitle_blur_strength, 18, 1, 100),
            removal_processing_device=processing_device_code(self.removal_processing_device.get()),
            propainter_license_accepted=bool(self.propainter_license_accepted.get()),
            audio_output_dir=self.audio_output_dir.get().strip(),
            audio_process_method=audio_method_code(self.audio_method.get()),
            audio_model_name=selected_audio_model.filename if selected_audio_model else "",
            audio_output_format=self.audio_format.get().strip().upper(),
            audio_segment_size=self.audio_segment_size.get().strip(),
            audio_overlap=self.audio_overlap.get().strip(),
            audio_processing_device=audio_device_code(self.audio_processing_device.get()),
            audio_gpu_conversion=bool(self.audio_gpu_conversion.get()),
            audio_vocals_only=bool(self.audio_vocals_only.get()),
            audio_instrumental_only=bool(self.audio_instrumental_only.get()),
            audio_sample_mode=bool(self.audio_sample_mode.get()),
            audio_saved_setting=self.audio_saved_setting.get().strip(),
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
        source_language = self._script_source_language()
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

    def _script_source_language(self) -> str:
        known_language = self.script_language_code.strip().lower()
        if known_language:
            return known_language
        return code_from_label(self.video_source_language.get(), default="auto")

    def _poll_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                self._append_log(str(payload))
            elif event == "audio_log":
                message = str(payload)
                self._append_audio_log(message)
                self._update_audio_progress_from_message(message)
            elif event == "task_progress":
                stage, completed, total = payload if isinstance(payload, tuple) else ("Working", 0, 0)
                completed_value = max(0, int(completed))
                total_value = max(0, int(total))
                if total_value:
                    self.progress.stop()
                    self.progress.configure(
                        mode="determinate",
                        maximum=total_value,
                        value=min(completed_value, total_value),
                    )
                    self.status.set(f"{stage} {completed_value}/{total_value}")
                else:
                    self.status.set(str(stage))
            elif event == "voices_loaded":
                engine_code, voices = payload if isinstance(payload, tuple) else ("", [])
                if engine_code == self.tts.code and isinstance(voices, list):
                    self._apply_voices(voices)
                    self._select_voice_for_language(self.script_language_code)
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
            elif event == "removal_preview_ready":
                session, source_path, preview_path, duration, position = (
                    payload if isinstance(payload, tuple) else (-1, "", payload, 0.0, 0.0)
                )
                if (
                    int(session) != self._removal_preview_session
                    or str(source_path) != str(Path(self.removal_video_path.get().strip()).expanduser())
                ):
                    continue
                self.progress.stop()
                self.removal_progress.stop()
                self._set_busy(False)
                self.status.set("Ready")
                self._load_removal_preview(
                    Path(preview_path),
                    float(duration),
                    float(position),
                )
                self._append_log("Video preview loaded.")
            elif event == "removal_preview_error":
                session, source_path, error = (
                    payload if isinstance(payload, tuple) else (-1, "", payload)
                )
                if (
                    int(session) != self._removal_preview_session
                    or str(source_path) != str(Path(self.removal_video_path.get().strip()).expanduser())
                ):
                    continue
                self._finish_error(error)
            elif event == "removal_playback_ended":
                session, position = payload if isinstance(payload, tuple) else (-1, 0.0)
                if int(session) == self._playback_session:
                    self._stop_removal_playback()
                    self._set_removal_timeline_position(float(position))
            elif event == "removal_playback_error":
                session, error = payload if isinstance(payload, tuple) else (-1, payload)
                if int(session) == self._playback_session:
                    self._stop_removal_playback()
                    self.status.set("Playback stopped")
                    self._append_log(f"Playback error: {error}")
                    messagebox.showerror("Playback failed", str(error))
            elif event == "audio_cancelled":
                self.audio_progress.stop()
                self.audio_progress.configure(mode="indeterminate", maximum=100, value=0)
                self._set_busy(False)
                self._active_task = None
                self.status.set("Stopped")
                self._append_audio_log(str(payload))
            elif event == "done":
                self._finish_success(payload)
            elif event == "error":
                self._finish_error(payload)

        self._render_latest_playback_frame()
        try:
            self._poll_after_id = self.root.after(60, self._poll_events)
        except tk.TclError:
            self._poll_after_id = None

    def _finish_success(self, result: object) -> None:
        self.progress.stop()
        self.removal_progress.stop()
        self.audio_progress.stop()
        self.progress.configure(mode="indeterminate", maximum=100, value=0)
        self.removal_progress.configure(mode="indeterminate", maximum=100, value=0)
        self.audio_progress.configure(mode="indeterminate", maximum=100, value=0)
        self._set_busy(False)
        self._active_task = None
        self.status.set("Done")
        self.open_button.configure(state="disabled")
        self.removal_open_button.configure(state="disabled")
        self.audio_open_button.configure(state="disabled")
        self.last_result = (
            result
            if isinstance(
                result,
                (
                    GenerationResult,
                    MediaExtractionResult,
                    VideoSubtitleResult,
                    SubtitleRemovalResult,
                    AudioSeparationResult,
                ),
            )
            else None
        )

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
            self._subtitle_draft_dirty = (
                self._subtitle_export_revision is not None
                and self._subtitle_edit_revision != self._subtitle_export_revision
            )
            self._subtitle_export_revision = None
            self.open_button.configure(state="normal")
            self._append_log(f"Audio: {self.last_result.audio_path}")
            self._append_log(f"Original SRT: {self.last_result.source_srt_path}")
            if self.last_result.translated_srt_path:
                self._append_log(f"Translated SRT: {self.last_result.translated_srt_path}")
            self._append_log(f"Manifest: {self.last_result.manifest_path}")
            for warning in self.last_result.warnings:
                self._append_log(f"Warning: {warning}")
        elif isinstance(self.last_result, SubtitleRemovalResult):
            self.removal_open_button.configure(state="normal")
            self._append_log(f"Video: {self.last_result.video_path}")
            self._append_log(f"Manifest: {self.last_result.manifest_path}")
            for warning in self.last_result.warnings:
                self._append_log(f"Warning: {warning}")
        elif isinstance(self.last_result, AudioSeparationResult):
            self.audio_open_button.configure(state="normal")
            self._append_audio_log("Output files:")
            for output_path in self.last_result.output_paths:
                self._append_audio_log(str(output_path))
            self._append_audio_log(f"Manifest: {self.last_result.manifest_path}")
            for warning in self.last_result.warnings:
                self._append_audio_log(f"Warning: {warning}")
            self._append_log(f"Audio stems: {self.last_result.project_dir}")

    def _finish_error(self, error: object) -> None:
        if isinstance(error, BaseException):
            log_operation_failure(LOGGER, "GUI task", error)
        self.progress.stop()
        self.removal_progress.stop()
        self.audio_progress.stop()
        self.progress.configure(mode="indeterminate", maximum=100, value=0)
        self.removal_progress.configure(mode="indeterminate", maximum=100, value=0)
        self.audio_progress.configure(mode="indeterminate", maximum=100, value=0)
        self._set_busy(False)
        audio_task_failed = self._active_task == "audio_separation"
        self._active_task = None
        self.status.set("Error")
        if self.last_result is None:
            self.open_button.configure(state="disabled")
            self.removal_open_button.configure(state="disabled")
            self.audio_open_button.configure(state="disabled")
        self._append_log(f"Error: {error}")
        if audio_task_failed:
            self._append_audio_log(f"Error: {error}")
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
        self._subtitle_draft_dirty = True
        self._subtitle_edit_revision = 0
        self._subtitle_export_revision = None

    def _confirm_discard_subtitle_draft(self, message: str) -> bool:
        if self.subtitle_draft is None or not self._subtitle_draft_dirty:
            return True
        return messagebox.askyesno("Phụ đề chưa export", message)

    def _discard_subtitle_draft(self) -> None:
        if self.subtitle_draft is not None:
            self.subtitle_draft.cleanup()
        self.subtitle_draft = None
        self._subtitle_draft_dirty = False
        self._subtitle_edit_revision = 0
        self._subtitle_export_revision = None
        self._set_editor_text(self.source_subtitle_text, "")
        self._set_editor_text(self.translated_subtitle_text, "")
        self.subtitle_export_button.configure(state="disabled")

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

    def _on_subtitle_modified(self, event: tk.Event) -> None:
        widget = event.widget
        if not isinstance(widget, tk.Text) or not widget.edit_modified():
            return
        if self.subtitle_draft is not None:
            self._subtitle_edit_revision += 1
            self._subtitle_draft_dirty = True
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
        self.voice_device_combo.configure(state="disabled" if busy else "readonly")
        self.removal_preview_button.configure(state=state)
        self.removal_process_button.configure(state=state)
        self.removal_mode_combo.configure(state="disabled" if busy else "readonly")
        self.removal_device_combo.configure(state="disabled" if busy else "readonly")
        if busy:
            self.propainter_install_button.configure(state="disabled")
        playback_state = "normal" if not busy and self.removal_duration_seconds > 0 else "disabled"
        self.removal_play_button.configure(state=playback_state)
        self.removal_timeline.configure(state=playback_state)
        if busy:
            for widget in self.removal_region_widgets:
                widget.configure(state="disabled")
        else:
            self._on_removal_mode_changed()

        for widget in self.audio_mutable_widgets:
            widget.configure(state=state)
        self.audio_process_button.configure(state=state)
        self.audio_stop_button.configure(
            state="normal" if busy and self._active_task == "audio_separation" else "disabled"
        )
        if not busy:
            self.audio_method_combo.configure(state="readonly")
            self.audio_segment_combo.configure(state="readonly")
            self.audio_overlap_combo.configure(state="readonly")
            self.audio_model_combo.configure(state="readonly")
            self.audio_preset_combo.configure(state="readonly")
            self._on_audio_gpu_changed()

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
        if not self._confirm_discard_subtitle_draft(
            "Đóng ứng dụng sẽ mất bản phụ đề chưa export. Vẫn đóng?"
        ):
            return
        self._save_config_now()
        self.root.destroy()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return

        self._stop_removal_playback(update_ui=False)
        managed_media_processes.terminate_all()

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

        try:
            self._preview_temp_dir.cleanup()
        except OSError:
            pass

def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def run_app() -> None:
    root = tk.Tk()
    GalaxyStudioApp(root)
    root.mainloop()
