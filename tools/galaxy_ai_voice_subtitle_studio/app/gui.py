from __future__ import annotations

import os
import queue
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .audio_separation.service import (
    AUDIO_SAVED_SETTINGS,
    AudioSeparationResult,
    audio_device_code,
    audio_device_label,
    audio_method_code,
    audio_method_label,
    discover_uvr_models,
    load_audio_presets,
    normalize_audio_method,
)
from .common.compute import (
    processing_device_code,
    processing_device_label,
)
from .common.config import AppConfig, default_config_path, load_app_config, save_app_config
from .common.diagnostics import get_logger, log_operation_failure
from .voice.engine import GenerationResult
from .voice.languages import code_from_label, label_from_code
from .voice.media import MediaExtractionResult
from .common.processes import managed_media_processes
from .subtitle_removal.service import (
    BLUR_MODE,
    SubtitleRemovalResult,
)
from .subtitle_removal.constants import REMOVAL_MODE_LABELS
from .voice.transcription import (
    VideoSubtitleDraft,
    VideoSubtitleResult,
)
from .voice.translator import (
    default_translation_api_key,
    default_translation_base_url,
    default_translation_model,
    default_translation_provider,
    translation_provider_code,
    translation_provider_label,
)
from .voice.tts import (
    TTSEngine,
    Voice,
    create_tts_engine,
    tts_engine_code,
)


from .audio_separation.gui import AudioSeparationTabMixin
from .subtitle_removal.gui import SubtitleRemovalTabMixin
from .voice.gui import VoiceTabMixin

LOGGER = get_logger("gui")


class GalaxyStudioApp(AudioSeparationTabMixin, SubtitleRemovalTabMixin, VoiceTabMixin):
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


    def _on_main_tab_changed(self, _event: tk.Event | None = None) -> None:
        selected_tab = self.main_notebook.select()
        if selected_tab != str(self.removal_tab):
            self._stop_removal_playback()
        if selected_tab == str(self.audio_tab):
            self.log_frame.grid_remove()
        else:
            self.log_frame.grid()


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

def run_app() -> None:
    root = tk.Tk()
    GalaxyStudioApp(root)
    root.mainloop()
