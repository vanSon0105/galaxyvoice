from __future__ import annotations

import math
import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from ..common.paths import studio_root
from .advanced_gui import OmniVoiceAdvancedGuiMixin
from .batch import OmniVoiceBatchResult
from .client import OmniVoiceWorkerClient
from .features import MODE_LABELS, NON_VERBAL_TAGS
from .models import (
    AUTO_MODE,
    CLONE_MODE,
    DESIGN_MODE,
    OmniVoiceGenerationOptions,
    OmniVoiceResult,
)
from .profiles import VoiceProfile, delete_voice_profile, list_voice_profiles
from .runtime import (
    DEVICE_LABELS,
    OmniVoiceRuntime,
    inspect_runtime,
    load_supported_language_ids,
    normalize_omnivoice_device,
    omnivoice_device_label,
    clear_model_cache,
    remove_runtime_engine,
)
from .service import generate_omnivoice_audio
from .workspaces.gui import OmniVoiceWorkspaceGuiMixin
from .workspaces.renderer import LongformWorkspaceResult


COMMON_LANGUAGES = (
    "vi",
    "en",
    "zh",
    "ja",
    "ko",
    "th",
    "id",
    "fr",
    "de",
    "es",
    "ru",
    "auto",
)
GENDER_CHOICES = {"Không chọn": "", "Nam": "male", "Nữ": "female"}
AGE_CHOICES = {
    "Không chọn": "",
    "Trẻ em": "child",
    "Thiếu niên": "teenager",
    "Thanh niên": "young adult",
    "Trung niên": "middle-aged",
    "Cao tuổi": "elderly",
}
PITCH_CHOICES = {
    "Không chọn": "",
    "Rất trầm": "very low pitch",
    "Trầm": "low pitch",
    "Trung bình": "moderate pitch",
    "Cao": "high pitch",
    "Rất cao": "very high pitch",
}
STYLE_CHOICES = {"Không chọn": "", "Thì thầm": "whisper"}
ACCENT_CHOICES = {
    "Không chọn": "",
    "Mỹ": "american accent",
    "Anh": "british accent",
    "Úc": "australian accent",
    "Canada": "canadian accent",
    "Ấn Độ": "indian accent",
    "Trung Quốc": "chinese accent",
    "Hàn Quốc": "korean accent",
    "Nhật Bản": "japanese accent",
    "Bồ Đào Nha": "portuguese accent",
    "Nga": "russian accent",
}
DIALECT_CHOICES = {
    "Không chọn": "",
    "Hà Nam": "河南话",
    "Thiểm Tây": "陕西话",
    "Tứ Xuyên": "四川话",
    "Quý Châu": "贵州话",
    "Vân Nam": "云南话",
    "Đông Bắc": "东北话",
}


class OmniVoiceTabMixin(OmniVoiceWorkspaceGuiMixin, OmniVoiceAdvancedGuiMixin):
    def _init_omnivoice_state(self, saved_config: object) -> None:
        self.omnivoice_runtime = OmniVoiceRuntime.default()
        self.omnivoice_language_values = (
            load_supported_language_ids(self.omnivoice_runtime) or COMMON_LANGUAGES
        )
        self.omnivoice_client = OmniVoiceWorkerClient(
            self.omnivoice_runtime,
            Path(__file__).with_name("worker.py"),
            log=lambda message: self.events.put(("omnivoice_log", message)),
        )
        self.omnivoice_task_thread: threading.Thread | None = None
        self.omnivoice_last_result: OmniVoiceResult | None = None
        self.omnivoice_last_batch_result: OmniVoiceBatchResult | None = None
        self._omnivoice_cancel_requested = False
        self.omnivoice_profiles: list[VoiceProfile] = []
        self._omnivoice_profile_by_label: dict[str, VoiceProfile] = {}

        output_default = (
            getattr(saved_config, "omnivoice_output_dir", "")
            or getattr(saved_config, "output_dir", "")
            or str(Path.cwd() / "exports")
        )
        self.omnivoice_output_dir = tk.StringVar(value=output_default)
        self.omnivoice_project_name = tk.StringVar(value="omnivoice")
        self.omnivoice_model_id = tk.StringVar(
            value=getattr(saved_config, "omnivoice_model_id", "k2-fsa/OmniVoice")
        )
        self.omnivoice_device = tk.StringVar(
            value=omnivoice_device_label(getattr(saved_config, "omnivoice_device", "auto"))
        )
        self.omnivoice_language = tk.StringVar(
            value=getattr(saved_config, "omnivoice_language", "vi")
        )
        self.omnivoice_num_step = tk.IntVar(
            value=getattr(saved_config, "omnivoice_num_step", 32)
        )
        self.omnivoice_guidance_scale = tk.DoubleVar(
            value=getattr(saved_config, "omnivoice_guidance_scale", 2.0)
        )
        self.omnivoice_t_shift = tk.DoubleVar(
            value=getattr(saved_config, "omnivoice_t_shift", 0.1)
        )
        self.omnivoice_layer_penalty_factor = tk.DoubleVar(
            value=getattr(saved_config, "omnivoice_layer_penalty_factor", 5.0)
        )
        self.omnivoice_position_temperature = tk.DoubleVar(
            value=getattr(saved_config, "omnivoice_position_temperature", 5.0)
        )
        self.omnivoice_class_temperature = tk.DoubleVar(
            value=getattr(saved_config, "omnivoice_class_temperature", 0.0)
        )
        self.omnivoice_speed = tk.DoubleVar(
            value=getattr(saved_config, "omnivoice_speed", 1.0)
        )
        self.omnivoice_duration = tk.DoubleVar(
            value=getattr(saved_config, "omnivoice_duration", 0.0)
        )
        self.omnivoice_denoise = tk.BooleanVar(
            value=getattr(saved_config, "omnivoice_denoise", True)
        )
        self.omnivoice_normalize_text = tk.BooleanVar(
            value=getattr(saved_config, "omnivoice_normalize_text", False)
        )
        self.omnivoice_preprocess_prompt = tk.BooleanVar(
            value=getattr(saved_config, "omnivoice_preprocess_prompt", True)
        )
        self.omnivoice_postprocess_output = tk.BooleanVar(
            value=getattr(saved_config, "omnivoice_postprocess_output", True)
        )
        self.omnivoice_audio_chunk_duration = tk.DoubleVar(
            value=getattr(saved_config, "omnivoice_audio_chunk_duration", 15.0)
        )
        self.omnivoice_audio_chunk_threshold = tk.DoubleVar(
            value=getattr(saved_config, "omnivoice_audio_chunk_threshold", 30.0)
        )
        self.omnivoice_pad_duration = tk.DoubleVar(
            value=getattr(saved_config, "omnivoice_pad_duration", 0.0)
        )
        self.omnivoice_fade_duration = tk.DoubleVar(
            value=getattr(saved_config, "omnivoice_fade_duration", 0.02)
        )
        self.omnivoice_export_mp3 = tk.BooleanVar(
            value=getattr(saved_config, "omnivoice_export_mp3", True)
        )
        self.omnivoice_enable_flashinfer = tk.BooleanVar(
            value=getattr(saved_config, "omnivoice_enable_flashinfer", False)
        )
        self.omnivoice_flashinfer_cuda_graph = tk.BooleanVar(
            value=getattr(saved_config, "omnivoice_flashinfer_cuda_graph", True)
        )
        self.omnivoice_lora_adapter = tk.StringVar(
            value=getattr(saved_config, "omnivoice_lora_adapter", "")
        )
        self.omnivoice_profile_choice = tk.StringVar(
            value=getattr(saved_config, "omnivoice_profile_id", "")
        )
        self.omnivoice_reference_audio = tk.StringVar()
        self.omnivoice_clone_instruct = tk.StringVar(
            value=getattr(saved_config, "omnivoice_clone_instruct", "")
        )
        self.omnivoice_save_profile_name = tk.StringVar()
        self.omnivoice_clone_consent = tk.BooleanVar(value=False)
        self.omnivoice_design_gender = tk.StringVar(
            value=_label_for_value(
                GENDER_CHOICES, getattr(saved_config, "omnivoice_design_gender", "")
            )
        )
        self.omnivoice_design_age = tk.StringVar(
            value=_label_for_value(AGE_CHOICES, getattr(saved_config, "omnivoice_design_age", ""))
        )
        self.omnivoice_design_pitch = tk.StringVar(
            value=_label_for_value(
                PITCH_CHOICES, getattr(saved_config, "omnivoice_design_pitch", "")
            )
        )
        self.omnivoice_design_style = tk.StringVar(
            value=_label_for_value(
                STYLE_CHOICES, getattr(saved_config, "omnivoice_design_style", "")
            )
        )
        self.omnivoice_design_accent = tk.StringVar(
            value=_label_for_value(
                ACCENT_CHOICES, getattr(saved_config, "omnivoice_design_accent", "")
            )
        )
        self.omnivoice_design_dialect = tk.StringVar(
            value=_label_for_value(
                DIALECT_CHOICES, getattr(saved_config, "omnivoice_design_dialect", "")
            )
        )
        self.omnivoice_runtime_status = tk.StringVar(value="Chưa kiểm tra runtime")
        self.omnivoice_worker_status = tk.StringVar(value="Model chưa nạp")
        self.omnivoice_job_status = tk.StringVar(value="Sẵn sàng")
        self.omnivoice_expression_choice = tk.StringVar(value=next(iter(NON_VERBAL_TAGS)))
        self.omnivoice_batch_mode = tk.StringVar(
            value=_label_for_value(
                MODE_LABELS, getattr(saved_config, "omnivoice_batch_mode", AUTO_MODE)
            )
        )
        self.omnivoice_long_form_mode = tk.StringVar(
            value=_label_for_value(
                MODE_LABELS, getattr(saved_config, "omnivoice_long_form_mode", AUTO_MODE)
            )
        )
        self.omnivoice_batch_project_name = tk.StringVar(value="omnivoice-batch")
        self.omnivoice_long_form_project_name = tk.StringVar(value="omnivoice-long-form")
        self.omnivoice_long_form_gap_ms = tk.IntVar(
            value=getattr(saved_config, "omnivoice_long_form_gap_ms", 250)
        )
        self.omnivoice_lora_merge_output = tk.StringVar()
        self.omnivoice_lora_status = tk.StringVar(value="Sẵn sàng")
        self._init_omnivoice_workspace_state()

    def _build_omnivoice_tabs(self, notebook: ttk.Notebook) -> None:
        self.omnivoice_text_widgets: dict[str, tk.Text] = {}
        self.omnivoice_generate_buttons: list[ttk.Button] = []
        self.omnivoice_stop_buttons: list[ttk.Button] = []
        self.omnivoice_open_buttons: list[ttk.Button] = []
        self.omnivoice_play_buttons: list[ttk.Button] = []
        self.omnivoice_progress_bars: list[ttk.Progressbar] = []
        self.omnivoice_mutable_widgets: list[tk.Widget] = []
        self.omnivoice_editable_combos: list[ttk.Combobox] = []
        self.omnivoice_language_combos: list[ttk.Combobox] = []
        self.omnivoice_profile_combos: list[ttk.Combobox] = []

        self.omnivoice_clone_tab = self._build_omnivoice_studio_page(
            notebook, "Voice Clone", CLONE_MODE
        )
        self.omnivoice_design_tab = self._build_omnivoice_studio_page(
            notebook, "Voice Design", DESIGN_MODE
        )
        self._build_omnivoice_workspace_tabs(notebook)
        notebook.insert(0, self.omnivoice_clone_tab)
        notebook.insert(1, self.omnivoice_design_tab)
        notebook.insert(2, self.classic_voice_tab)
        notebook.tab(self.classic_voice_tab, text="Video Dubbing")
        self._refresh_omnivoice_profiles()
        self._refresh_omnivoice_runtime_status()

    def _build_omnivoice_studio_page(
        self,
        notebook: ttk.Notebook,
        title: str,
        mode: str,
    ) -> ttk.Frame:
        page = ttk.Frame(notebook, padding=12)
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2, minsize=330)
        page.rowconfigure(0, weight=1)
        notebook.add(page, text=title)

        editor = ttk.Frame(page)
        editor.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(2, weight=1)
        ttk.Label(editor, text="Nội dung", style="PageSection.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        text_tools = ttk.Frame(editor, style="Surface.TFrame")
        text_tools.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        text_tools.columnconfigure(0, weight=1)
        expression = ttk.Combobox(
            text_tools,
            textvariable=self.omnivoice_expression_choice,
            values=tuple(NON_VERBAL_TAGS),
            state="readonly",
            width=18,
        )
        expression.grid(row=0, column=0, sticky="ew")
        insert_expression = ttk.Button(
            text_tools,
            text="Chèn biểu cảm",
            command=lambda selected_mode=mode: self._insert_omnivoice_expression(selected_mode),
        )
        insert_expression.grid(row=0, column=1, padx=(6, 0))
        cmu = ttk.Button(
            text_tools,
            text="CMU",
            command=lambda selected_mode=mode: self._insert_omnivoice_pronunciation(
                selected_mode, "cmu"
            ),
        )
        cmu.grid(row=0, column=2, padx=(6, 0))
        pinyin = ttk.Button(
            text_tools,
            text="Pinyin",
            command=lambda selected_mode=mode: self._insert_omnivoice_pronunciation(
                selected_mode, "pinyin"
            ),
        )
        pinyin.grid(row=0, column=3, padx=(6, 0))
        text_frame = ttk.Frame(editor, style="Panel.TFrame")
        text_frame.grid(row=2, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        text_widget = tk.Text(
            text_frame,
            wrap="word",
            font=("Segoe UI", 11),
            relief="flat",
            padx=12,
            pady=10,
            undo=True,
        )
        text_widget.grid(row=0, column=0, sticky="nsew")
        text_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        text_scroll.grid(row=0, column=1, sticky="ns")
        text_widget.configure(yscrollcommand=text_scroll.set)
        self.omnivoice_text_widgets[mode] = text_widget
        self.omnivoice_mutable_widgets.extend(
            (expression, insert_expression, cmu, pinyin, text_widget)
        )

        controls_host = ttk.Frame(page, style="Panel.TFrame", padding=12)
        controls_host.grid(row=0, column=1, sticky="nsew")
        controls_host.columnconfigure(0, weight=1)
        controls_host.rowconfigure(0, weight=1)
        controls = self._build_omnivoice_scrollable_controls(controls_host)

        row = 0
        if mode == CLONE_MODE:
            row = self._build_clone_controls(controls, row)
        elif mode == DESIGN_MODE:
            row = self._build_design_controls(controls, row)
        row = self._build_common_generation_controls(controls, row)

        actions = ttk.Frame(controls_host, style="Surface.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure((0, 1, 2, 3), weight=1)
        generate = ttk.Button(
            actions,
            text="Tạo giọng",
            style="Accent.TButton",
            command=lambda selected_mode=mode: self._start_omnivoice_generation(selected_mode),
        )
        generate.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        stop = ttk.Button(actions, text="Dừng", command=self._stop_omnivoice, state="disabled")
        stop.grid(row=0, column=1, sticky="ew", padx=3)
        play_button = ttk.Button(
            actions,
            text="Nghe",
            command=self._play_omnivoice_result,
            state="disabled",
        )
        play_button.grid(row=0, column=2, sticky="ew", padx=3)
        open_button = ttk.Button(
            actions,
            text="Mở output",
            command=self._open_omnivoice_output,
            state="disabled",
        )
        open_button.grid(row=0, column=3, sticky="ew", padx=(6, 0))
        progress = ttk.Progressbar(controls_host, mode="indeterminate")
        progress.grid(row=2, column=0, sticky="ew", pady=(9, 0))
        ttk.Label(
            controls_host,
            textvariable=self.omnivoice_job_status,
            style="Panel.TLabel",
        ).grid(row=3, column=0, sticky="w", pady=(5, 0))

        self.omnivoice_generate_buttons.append(generate)
        self.omnivoice_stop_buttons.append(stop)
        self.omnivoice_open_buttons.append(open_button)
        self.omnivoice_play_buttons.append(play_button)
        self.omnivoice_progress_bars.append(progress)
        return page

    def _build_clone_controls(self, parent: ttk.Frame, row: int) -> int:
        ttk.Label(parent, text="Giọng mẫu", style="Section.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        row += 1
        ttk.Label(parent, text="Profile đã lưu", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        self.omnivoice_profile_combo = ttk.Combobox(
            parent,
            textvariable=self.omnivoice_profile_choice,
            state="readonly",
        )
        self.omnivoice_profile_combo.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(3, 8))
        self.omnivoice_mutable_widgets.append(self.omnivoice_profile_combo)
        self.omnivoice_profile_combos.append(self.omnivoice_profile_combo)
        row += 1
        ttk.Label(parent, text="Audio tham chiếu", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        ref_entry = ttk.Entry(parent, textvariable=self.omnivoice_reference_audio)
        ref_entry.grid(row=row, column=0, sticky="ew", pady=(3, 8))
        browse = ttk.Button(parent, text="Chọn", command=self._browse_omnivoice_reference)
        browse.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=(3, 8))
        self.omnivoice_mutable_widgets.extend((ref_entry, browse))
        row += 1
        ttk.Label(parent, text="Transcript audio mẫu", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        self.omnivoice_reference_text = tk.Text(parent, height=4, wrap="word", font=("Segoe UI", 9))
        self.omnivoice_reference_text.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(3, 8))
        self.omnivoice_mutable_widgets.append(self.omnivoice_reference_text)
        row += 1
        ttk.Label(parent, text="Mô tả giọng mẫu (tùy chọn)", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        clone_instruct = ttk.Entry(parent, textvariable=self.omnivoice_clone_instruct)
        clone_instruct.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(3, 8))
        self.omnivoice_mutable_widgets.append(clone_instruct)
        row += 1
        ttk.Label(parent, text="Lưu thành profile mới", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        profile_name = ttk.Entry(parent, textvariable=self.omnivoice_save_profile_name)
        profile_name.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(3, 6))
        consent = ttk.Checkbutton(
            parent,
            text="Tôi có quyền sử dụng giọng nói này",
            variable=self.omnivoice_clone_consent,
        )
        consent.grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.omnivoice_mutable_widgets.extend((profile_name, consent))
        return row + 2

    def _build_design_controls(self, parent: ttk.Frame, row: int) -> int:
        ttk.Label(parent, text="Đặc điểm giọng", style="Section.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        row += 1
        fields = (
            ("Giới tính", self.omnivoice_design_gender, GENDER_CHOICES),
            ("Độ tuổi", self.omnivoice_design_age, AGE_CHOICES),
            ("Cao độ", self.omnivoice_design_pitch, PITCH_CHOICES),
            ("Phong cách", self.omnivoice_design_style, STYLE_CHOICES),
            ("Accent tiếng Anh", self.omnivoice_design_accent, ACCENT_CHOICES),
            ("Phương ngữ Trung", self.omnivoice_design_dialect, DIALECT_CHOICES),
        )
        for label, variable, choices in fields:
            ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w")
            combo = ttk.Combobox(
                parent,
                textvariable=variable,
                values=tuple(choices),
                state="readonly",
                width=18,
            )
            combo.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
            self.omnivoice_mutable_widgets.append(combo)
            row += 1
        ttk.Label(parent, text="Mô tả bổ sung", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )
        row += 1
        self.omnivoice_custom_instruct = tk.Text(parent, height=3, wrap="word", font=("Segoe UI", 9))
        self.omnivoice_custom_instruct.grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(3, 10)
        )
        self.omnivoice_mutable_widgets.append(self.omnivoice_custom_instruct)
        return row + 1

    def _build_common_generation_controls(self, parent: ttk.Frame, row: int) -> int:
        ttk.Separator(parent).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(2, 10))
        row += 1
        ttk.Label(parent, text="Thiết lập tạo giọng", style="Section.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 5)
        )
        row += 1
        ttk.Label(parent, text="Ngôn ngữ", style="Panel.TLabel").grid(row=row, column=0, sticky="w")
        language = ttk.Combobox(
            parent,
            textvariable=self.omnivoice_language,
            values=self.omnivoice_language_values,
            state="normal",
            width=16,
        )
        language.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
        self.omnivoice_editable_combos.append(language)
        self.omnivoice_language_combos.append(language)
        row += 1
        ttk.Label(parent, text="Quality steps", style="Panel.TLabel").grid(row=row, column=0, sticky="w")
        steps = ttk.Combobox(
            parent,
            textvariable=self.omnivoice_num_step,
            values=(16, 32, 48, 64),
            state="readonly",
            width=16,
        )
        steps.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
        row += 1
        ttk.Label(parent, text="Tốc độ", style="Panel.TLabel").grid(row=row, column=0, sticky="w")
        speed = ttk.Scale(
            parent,
            from_=0.5,
            to=1.5,
            variable=self.omnivoice_speed,
            orient="horizontal",
        )
        speed.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
        row += 1
        ttk.Label(parent, text="Guidance", style="Panel.TLabel").grid(row=row, column=0, sticky="w")
        guidance = ttk.Scale(
            parent,
            from_=0.0,
            to=4.0,
            variable=self.omnivoice_guidance_scale,
            orient="horizontal",
        )
        guidance.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
        row += 1
        advanced_fields = (
            ("Thời lượng (0 = tự động)", self.omnivoice_duration),
            ("T-shift", self.omnivoice_t_shift),
            ("Layer penalty", self.omnivoice_layer_penalty_factor),
            ("Position temperature", self.omnivoice_position_temperature),
            ("Class temperature", self.omnivoice_class_temperature),
            ("Độ dài chunk", self.omnivoice_audio_chunk_duration),
            ("Ngưỡng chia chunk", self.omnivoice_audio_chunk_threshold),
            ("Đệm đầu/cuối (0 = cắt sát)", self.omnivoice_pad_duration),
            ("Fade chống click", self.omnivoice_fade_duration),
        )
        advanced_widgets: list[ttk.Entry] = []
        for label, variable in advanced_fields:
            ttk.Label(parent, text=label, style="Panel.TLabel").grid(
                row=row, column=0, sticky="w", pady=2
            )
            entry = ttk.Entry(parent, textvariable=variable, width=12)
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2)
            advanced_widgets.append(entry)
            row += 1
        toggles = (
            ("Denoise", self.omnivoice_denoise),
            ("Chuẩn hóa chữ và số", self.omnivoice_normalize_text),
            ("Xử lý audio mẫu", self.omnivoice_preprocess_prompt),
            ("Cắt im lặng đầu/cuối", self.omnivoice_postprocess_output),
            ("Xuất thêm MP3", self.omnivoice_export_mp3),
            ("FlashInfer", self.omnivoice_enable_flashinfer),
            ("FlashInfer CUDA Graph", self.omnivoice_flashinfer_cuda_graph),
        )
        toggle_widgets: list[ttk.Checkbutton] = []
        for label, variable in toggles:
            toggle = ttk.Checkbutton(parent, text=label, variable=variable)
            toggle.grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
            toggle_widgets.append(toggle)
            row += 1
        ttk.Label(parent, text="LoRA adapter (tùy chọn)", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        row += 1
        lora_entry = ttk.Entry(parent, textvariable=self.omnivoice_lora_adapter)
        lora_entry.grid(row=row, column=0, sticky="ew", pady=(3, 5))
        lora_browse = ttk.Button(parent, text="Chọn", command=self._browse_omnivoice_lora)
        lora_browse.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=(3, 5))
        row += 1
        ttk.Label(parent, text="Tên project", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        row += 1
        project = ttk.Entry(parent, textvariable=self.omnivoice_project_name)
        project.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(3, 5))
        row += 1
        ttk.Label(parent, text="Thư mục output", style="Panel.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        output = ttk.Entry(parent, textvariable=self.omnivoice_output_dir)
        output.grid(row=row, column=0, sticky="ew", pady=(3, 0))
        output_browse = ttk.Button(parent, text="Chọn", command=self._browse_omnivoice_output)
        output_browse.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=(3, 0))
        self.omnivoice_mutable_widgets.extend(
            (
                language,
                steps,
                speed,
                guidance,
                *advanced_widgets,
                *toggle_widgets,
                lora_entry,
                lora_browse,
                project,
                output,
                output_browse,
            )
        )
        return row + 1

    def _build_omnivoice_library_tab(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=12)
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2, minsize=300)
        page.rowconfigure(0, weight=1)
        notebook.add(page, text="Thư viện giọng")
        self.omnivoice_library_tab = page

        tree_frame = ttk.Frame(page, style="Panel.TFrame", padding=8)
        tree_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.omnivoice_profile_tree = ttk.Treeview(
            tree_frame,
            columns=("name", "language", "created"),
            show="headings",
            selectmode="browse",
        )
        self.omnivoice_profile_tree.heading("name", text="Tên giọng")
        self.omnivoice_profile_tree.heading("language", text="Ngôn ngữ")
        self.omnivoice_profile_tree.heading("created", text="Ngày tạo")
        self.omnivoice_profile_tree.column("name", width=210, stretch=True)
        self.omnivoice_profile_tree.column("language", width=90, stretch=False)
        self.omnivoice_profile_tree.column("created", width=150, stretch=False)
        self.omnivoice_profile_tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.omnivoice_profile_tree.yview
        )
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.omnivoice_profile_tree.configure(yscrollcommand=tree_scroll.set)
        self.omnivoice_profile_tree.bind("<<TreeviewSelect>>", self._show_selected_profile)

        details = ttk.Frame(page, style="Panel.TFrame", padding=12)
        details.grid(row=0, column=1, sticky="nsew")
        details.columnconfigure(0, weight=1)
        details.rowconfigure(1, weight=1)
        ttk.Label(details, text="Chi tiết profile", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.omnivoice_profile_details = tk.Text(
            details,
            height=12,
            wrap="word",
            font=("Segoe UI", 9),
            state="disabled",
        )
        self.omnivoice_profile_details.grid(row=1, column=0, sticky="nsew")
        actions = ttk.Frame(details, style="Surface.TFrame")
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure((0, 1), weight=1)
        buttons = (
            ("Dùng profile", self._use_selected_profile),
            ("Nghe audio mẫu", self._play_selected_profile_reference),
            ("Xóa profile", self._delete_selected_profile),
            ("Mở thư mục", self._open_omnivoice_profiles),
        )
        for index, (label, command) in enumerate(buttons):
            button = ttk.Button(actions, text=label, command=command)
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=3, pady=3)

    def _build_omnivoice_runtime_tab(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=12)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        notebook.add(page, text="Model & Runtime")
        self.omnivoice_runtime_tab = page

        settings = ttk.Frame(page, style="Panel.TFrame", padding=12)
        settings.grid(row=0, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="Runtime", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(settings, textvariable=self.omnivoice_runtime_status, style="Panel.TLabel").grid(
            row=0, column=1, sticky="w", padx=(12, 0)
        )
        ttk.Label(settings, text="Worker", style="Section.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(settings, textvariable=self.omnivoice_worker_status, style="Panel.TLabel").grid(
            row=1, column=1, sticky="w", padx=(12, 0)
        )
        ttk.Label(settings, text="Model", style="Panel.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        model_entry = ttk.Entry(settings, textvariable=self.omnivoice_model_id)
        model_entry.grid(row=2, column=1, sticky="ew", padx=(12, 0), pady=(8, 0))
        ttk.Label(settings, text="Thiết bị", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.omnivoice_device_combo = ttk.Combobox(
            settings,
            textvariable=self.omnivoice_device,
            values=tuple(DEVICE_LABELS.values()),
            state="readonly",
        )
        self.omnivoice_device_combo.grid(row=3, column=1, sticky="ew", padx=(12, 0), pady=(6, 0))
        self.omnivoice_mutable_widgets.extend((model_entry, self.omnivoice_device_combo))

        actions = ttk.Frame(settings, style="Surface.TFrame")
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        for column in range(4):
            actions.columnconfigure(column, weight=1)
        controls = (
            ("Kiểm tra", self._probe_omnivoice_runtime),
            ("Cài / sửa runtime", self._install_omnivoice_runtime),
            ("Cài FlashInfer", self._install_omnivoice_flashinfer),
            ("Chọn model local", self._browse_omnivoice_model),
            ("Tải model", self._load_omnivoice_model),
            ("Giải phóng VRAM", self._unload_omnivoice_model),
            ("Xóa model cache", self._clear_omnivoice_model_cache),
            ("Gỡ runtime", self._remove_omnivoice_runtime),
            ("Mở thư mục", self._open_omnivoice_runtime),
        )
        for index, (label, command) in enumerate(controls):
            button = ttk.Button(actions, text=label, command=command)
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=3, pady=3)
            if label != "Mở thư mục":
                self.omnivoice_mutable_widgets.append(button)

        log_frame = ttk.Frame(page, style="Panel.TFrame", padding=8)
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        ttk.Label(log_frame, text="OmniVoice log", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 5)
        )
        self.omnivoice_log_text = tk.Text(
            log_frame,
            wrap="word",
            font=("Consolas", 9),
            bg="#202522",
            fg="#e9f1ec",
            relief="flat",
            state="disabled",
        )
        self.omnivoice_log_text.grid(row=1, column=0, sticky="nsew")

    def _build_omnivoice_scrollable_controls(self, parent: ttk.Frame) -> ttk.Frame:
        canvas = tk.Canvas(parent, bg="#ffffff", highlightthickness=0, width=310)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas, style="Surface.TFrame")
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)
        window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        content.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window, width=max(1, event.width)),
        )
        canvas.bind("<MouseWheel>", self._on_controls_mousewheel)
        content.bind("<MouseWheel>", self._on_controls_mousewheel)
        return content

    def _start_omnivoice_generation(self, mode: str) -> None:
        if self._active_task is not None:
            return
        status = inspect_runtime(self.omnivoice_runtime)
        if not status.installed:
            messagebox.showerror("OmniVoice chưa được cài", status.message)
            self._select_omnivoice_runtime()
            return
        text = self.omnivoice_text_widgets[mode].get("1.0", "end").strip()
        try:
            options = self._omnivoice_options(mode, text, bulk=False)
        except (OSError, ValueError) as error:
            messagebox.showerror("Thiết lập OmniVoice chưa hợp lệ", str(error))
            return
        self._start_omnivoice_thread(
            "omnivoice_generation",
            self._run_omnivoice_generation,
            (options,),
            "omnivoice-generate",
        )

    def _omnivoice_options(
        self,
        mode: str,
        text: str,
        *,
        bulk: bool,
        project_name: str | None = None,
    ) -> OmniVoiceGenerationOptions:
        profile = self._selected_omnivoice_profile()
        reference_text = (
            self.omnivoice_reference_text.get("1.0", "end").strip()
            if mode == CLONE_MODE
            else ""
        )
        if mode == CLONE_MODE and bulk and profile is None:
            raise ValueError("Batch và long-form cần chọn một profile giọng đã lưu.")
        if mode == CLONE_MODE and profile is None and not self.omnivoice_clone_consent.get():
            raise ValueError("Hãy xác nhận bạn có quyền sử dụng giọng nói trong audio mẫu.")
        reference_value = self.omnivoice_reference_audio.get().strip()
        reference_audio = Path(reference_value).expanduser() if reference_value else None
        if mode == DESIGN_MODE:
            instruct = self._omnivoice_design_instruction()
        elif mode == CLONE_MODE:
            instruct = self.omnivoice_clone_instruct.get().strip()
        else:
            instruct = ""
        return OmniVoiceGenerationOptions(
            mode=mode,
            text=text,
            output_dir=Path(self.omnivoice_output_dir.get().strip()).expanduser(),
            project_name=(
                project_name
                if project_name is not None
                else self.omnivoice_project_name.get().strip() or f"omnivoice-{mode}"
            ),
            model_id=self.omnivoice_model_id.get().strip(),
            device=normalize_omnivoice_device(self.omnivoice_device.get()),
            language=self.omnivoice_language.get().strip() or "auto",
            reference_audio=reference_audio,
            reference_text=reference_text,
            profile_id=profile.profile_id if profile else "",
            save_profile_name="" if bulk else self.omnivoice_save_profile_name.get().strip(),
            profiles_dir=self.omnivoice_runtime.profiles_dir,
            instruct=instruct,
            num_step=self._safe_int(self.omnivoice_num_step, 32),
            guidance_scale=self._safe_float(self.omnivoice_guidance_scale, 2.0),
            t_shift=self._safe_float(self.omnivoice_t_shift, 0.1),
            layer_penalty_factor=self._safe_float(
                self.omnivoice_layer_penalty_factor, 5.0
            ),
            position_temperature=self._safe_float(
                self.omnivoice_position_temperature, 5.0
            ),
            class_temperature=self._safe_float(self.omnivoice_class_temperature, 0.0),
            speed=self._safe_float(self.omnivoice_speed, 1.0),
            duration=(
                self._safe_float(self.omnivoice_duration, 0.0)
                if self._safe_float(self.omnivoice_duration, 0.0) > 0
                else None
            ),
            denoise=bool(self.omnivoice_denoise.get()),
            normalize_text=bool(self.omnivoice_normalize_text.get()),
            preprocess_prompt=bool(self.omnivoice_preprocess_prompt.get()),
            postprocess_output=bool(self.omnivoice_postprocess_output.get()),
            audio_chunk_duration=self._safe_float(
                self.omnivoice_audio_chunk_duration, 15.0
            ),
            audio_chunk_threshold=self._safe_float(
                self.omnivoice_audio_chunk_threshold, 30.0
            ),
            pad_duration=self._safe_float(self.omnivoice_pad_duration, 0.0),
            fade_duration=self._safe_float(self.omnivoice_fade_duration, 0.02),
            export_mp3=bool(self.omnivoice_export_mp3.get()),
            enable_flashinfer=bool(self.omnivoice_enable_flashinfer.get()),
            flashinfer_cuda_graph=bool(self.omnivoice_flashinfer_cuda_graph.get()),
            lora_adapter=self.omnivoice_lora_adapter.get().strip(),
        )

    def _start_omnivoice_thread(
        self,
        task_name: str,
        target: Callable[..., None],
        args: tuple[object, ...],
        thread_name: str,
    ) -> None:
        self._omnivoice_cancel_requested = False
        self._active_task = task_name
        self.omnivoice_job_status.set("Đang khởi động OmniVoice...")
        self._set_busy(True)
        for progress in self.omnivoice_progress_bars:
            progress.start(12)
        self.omnivoice_task_thread = threading.Thread(
            target=target,
            args=args,
            daemon=True,
            name=thread_name,
        )
        self.omnivoice_task_thread.start()

    def _run_omnivoice_generation(self, options: OmniVoiceGenerationOptions) -> None:
        try:
            result = generate_omnivoice_audio(
                options,
                self.omnivoice_client,
                progress=lambda message: self.events.put(("omnivoice_progress", message)),
            )
        except Exception as error:
            event = "omnivoice_cancelled" if self._omnivoice_cancel_requested else "omnivoice_error"
            self.events.put((event, error))
        else:
            self.events.put(("omnivoice_done", result))

    def _load_omnivoice_model(self) -> None:
        if self._active_task is not None:
            return
        status = inspect_runtime(self.omnivoice_runtime)
        if not status.installed:
            messagebox.showerror("OmniVoice chưa được cài", status.message)
            return
        self._omnivoice_cancel_requested = False
        self._active_task = "omnivoice_model"
        self._set_busy(True)
        self.omnivoice_worker_status.set("Đang tải model...")
        model_id = self.omnivoice_model_id.get().strip()
        device = normalize_omnivoice_device(self.omnivoice_device.get())
        lora_adapter = self.omnivoice_lora_adapter.get().strip()
        enable_flashinfer = bool(self.omnivoice_enable_flashinfer.get())
        flashinfer_cuda_graph = bool(self.omnivoice_flashinfer_cuda_graph.get())

        def run() -> None:
            try:
                payload = self.omnivoice_client.request(
                    "load",
                    {
                        "model_id": model_id,
                        "device": device,
                        "lora_adapter": lora_adapter,
                        "enable_flashinfer": enable_flashinfer,
                        "flashinfer_cuda_graph": flashinfer_cuda_graph,
                    },
                    on_progress=lambda message: self.events.put(("omnivoice_progress", message)),
                )
            except Exception as error:
                event = "omnivoice_cancelled" if self._omnivoice_cancel_requested else "omnivoice_error"
                self.events.put((event, error))
            else:
                self.events.put(("omnivoice_model_loaded", payload))

        self.omnivoice_task_thread = threading.Thread(
            target=run,
            daemon=True,
            name="omnivoice-load",
        )
        self.omnivoice_task_thread.start()

    def _probe_omnivoice_runtime(self) -> None:
        if self._active_task is not None:
            return
        status = inspect_runtime(self.omnivoice_runtime)
        if not status.installed:
            self._refresh_omnivoice_runtime_status()
            messagebox.showerror("OmniVoice chưa được cài", status.message)
            return
        self._active_task = "omnivoice_probe"
        self._omnivoice_cancel_requested = False
        self._set_busy(True)
        self.omnivoice_runtime_status.set("Đang kiểm tra dependency...")

        def run() -> None:
            try:
                payload = self.omnivoice_client.request("probe", {})
            except Exception as error:
                event = "omnivoice_cancelled" if self._omnivoice_cancel_requested else "omnivoice_error"
                self.events.put((event, error))
            else:
                self.events.put(("omnivoice_runtime_probed", payload))

        self.omnivoice_task_thread = threading.Thread(
            target=run,
            daemon=True,
            name="omnivoice-probe",
        )
        self.omnivoice_task_thread.start()

    def _unload_omnivoice_model(self) -> None:
        self.omnivoice_client.stop()
        self.omnivoice_worker_status.set("Model chưa nạp")
        self._append_omnivoice_log("Đã dừng worker và giải phóng model.")

    def _stop_omnivoice(self) -> None:
        if self._active_task not in {
            "omnivoice_generation",
            "omnivoice_batch",
            "omnivoice_long_form",
            "omnivoice_stories",
            "omnivoice_audiobook",
            "omnivoice_dub",
            "omnivoice_model",
            "omnivoice_probe",
            "omnivoice_lora_merge",
        }:
            return
        self._omnivoice_cancel_requested = True
        self.omnivoice_job_status.set("Đang dừng OmniVoice...")
        for button in self.omnivoice_stop_buttons:
            button.configure(state="disabled")
        threading.Thread(
            target=self.omnivoice_client.stop,
            daemon=True,
            name="omnivoice-stop",
        ).start()

    def _handle_omnivoice_event(self, event: str, payload: object) -> bool:
        if not event.startswith("omnivoice_"):
            return False
        if event == "omnivoice_log":
            self._append_omnivoice_log(str(payload))
            return True
        if event == "omnivoice_progress":
            message = str(payload)
            self.omnivoice_job_status.set(message)
            self.status.set(message)
            self._append_omnivoice_log(message)
            return True

        for progress in self.omnivoice_progress_bars:
            progress.stop()
        self._active_task = None
        self._set_busy(False)
        if event == "omnivoice_workspace_done" and isinstance(payload, tuple):
            kind, result = payload
            if isinstance(result, LongformWorkspaceResult):
                self._finish_omnivoice_workspace(str(kind), result)
        elif event == "omnivoice_done" and isinstance(payload, OmniVoiceResult):
            self.omnivoice_last_result = payload
            self.omnivoice_last_batch_result = None
            self.omnivoice_workspace_result = None
            self.omnivoice_job_status.set("Hoàn tất")
            self.status.set("Done")
            for button in self.omnivoice_open_buttons:
                button.configure(state="normal")
            for button in self.omnivoice_play_buttons:
                button.configure(state="normal")
            self._append_omnivoice_log(f"WAV: {payload.wav_path}")
            if payload.mp3_path:
                self._append_omnivoice_log(f"MP3: {payload.mp3_path}")
            if payload.profile_id:
                self._append_omnivoice_log(f"Đã lưu profile: {payload.profile_id}")
                self._refresh_omnivoice_profiles()
            for warning in payload.warnings:
                self._append_omnivoice_log(f"Cảnh báo: {warning}")
        elif event == "omnivoice_batch_done" and isinstance(payload, OmniVoiceBatchResult):
            self.omnivoice_last_result = None
            self.omnivoice_last_batch_result = payload
            self.omnivoice_workspace_result = None
            self.omnivoice_job_status.set("Hoàn tất")
            self.status.set("Done")
            for button in self.omnivoice_open_buttons:
                button.configure(state="normal")
            for button in self.omnivoice_play_buttons:
                button.configure(state="normal" if payload.preview_path else "disabled")
            self._append_omnivoice_log(f"Batch output: {payload.project_dir}")
            self._append_omnivoice_log(f"Đã tạo {len(payload.item_results)} mục.")
            if payload.combined_wav_path:
                self._append_omnivoice_log(f"WAV đã ghép: {payload.combined_wav_path}")
            for warning in payload.warnings:
                self._append_omnivoice_log(f"Cảnh báo: {warning}")
        elif event == "omnivoice_model_loaded" and isinstance(payload, dict):
            device = str(payload.get("device") or "")
            self.omnivoice_worker_status.set(f"Đã nạp model trên {device}")
            self.omnivoice_job_status.set("Model sẵn sàng")
            self.status.set("Ready")
            self._append_omnivoice_log(
                f"Model {payload.get('model_id', '')} đã nạp trên {device}."
            )
            languages = payload.get("languages")
            if isinstance(languages, list) and languages:
                values = tuple(str(value) for value in languages)
                for combo in self.omnivoice_language_combos:
                    combo.configure(values=values)
                self._append_omnivoice_log(f"Đã nạp {len(values)} ngôn ngữ.")
            if payload.get("flashinfer"):
                graph = " + CUDA Graph" if payload.get("flashinfer_cuda_graph") else ""
                self._append_omnivoice_log(f"FlashInfer{graph} đang bật.")
            if payload.get("lora_adapter"):
                self._append_omnivoice_log(f"LoRA: {payload.get('lora_adapter')}")
        elif event == "omnivoice_lora_merged" and isinstance(payload, dict):
            output_dir = str(payload.get("output_dir") or "")
            self.omnivoice_job_status.set("Merge LoRA hoàn tất")
            self.status.set("Done")
            self.omnivoice_lora_status.set("Merge hoàn tất")
            if output_dir:
                self.omnivoice_model_id.set(output_dir)
                self.omnivoice_lora_adapter.set("")
                self._append_omnivoice_log(f"Model LoRA đã merge: {output_dir}")
        elif event == "omnivoice_runtime_probed" and isinstance(payload, dict):
            accelerator = "CUDA" if payload.get("cuda") else "XPU" if payload.get("xpu") else "CPU"
            self.omnivoice_runtime_status.set(
                f"OmniVoice {payload.get('omnivoice_version', '')} | "
                f"Torch {payload.get('torch_version', '')} | {accelerator} | "
                f"FlashInfer {'OK' if payload.get('flashinfer') else 'chưa cài'} | "
                f"LoRA {'OK' if payload.get('peft') else 'chưa cài'}"
            )
            self.omnivoice_worker_status.set("Worker sẵn sàng; model chưa nạp")
            self.omnivoice_job_status.set("Runtime sẵn sàng")
            self.status.set("Ready")
        elif event == "omnivoice_cancelled":
            self.omnivoice_job_status.set("Đã dừng")
            self.omnivoice_worker_status.set("Model chưa nạp")
            self.status.set("Stopped")
            self._append_omnivoice_log("Đã dừng tác vụ OmniVoice.")
        elif event == "omnivoice_error":
            self.omnivoice_job_status.set("Lỗi")
            self.status.set("Error")
            self._append_omnivoice_log(f"Lỗi: {payload}")
            messagebox.showerror("OmniVoice thất bại", str(payload))
        return True

    def _set_omnivoice_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for widget in self.omnivoice_mutable_widgets:
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        if not busy:
            for widget in self.omnivoice_mutable_widgets:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(
                        state="normal" if widget in self.omnivoice_editable_combos else "readonly"
                    )
            for text_widget in self.omnivoice_text_widgets.values():
                text_widget.configure(state="normal")
        for button in self.omnivoice_generate_buttons:
            button.configure(state=state)
        is_omnivoice_task = busy and self._active_task in {
            "omnivoice_generation",
            "omnivoice_batch",
            "omnivoice_long_form",
            "omnivoice_stories",
            "omnivoice_audiobook",
            "omnivoice_dub",
            "omnivoice_model",
            "omnivoice_probe",
            "omnivoice_lora_merge",
        }
        for button in self.omnivoice_stop_buttons:
            button.configure(state="normal" if is_omnivoice_task else "disabled")

    def _refresh_omnivoice_runtime_status(self) -> None:
        status = inspect_runtime(self.omnivoice_runtime)
        self.omnivoice_runtime_status.set(status.message)
        self.omnivoice_worker_status.set(
            "Worker đang chạy" if self.omnivoice_client.is_running else "Model chưa nạp"
        )

    def _install_omnivoice_runtime(self) -> None:
        installer = studio_root() / "install_omnivoice.ps1"
        if not installer.is_file():
            messagebox.showerror("Thiếu bộ cài", f"Không tìm thấy {installer}")
            return
        device = normalize_omnivoice_device(self.omnivoice_device.get())
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
                    "-Device",
                    device,
                ],
                cwd=str(studio_root()),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        except OSError as error:
            messagebox.showerror("Không mở được bộ cài", str(error))
            return
        self._append_omnivoice_log("Đã mở cửa sổ cài OmniVoice runtime.")

    def _browse_omnivoice_model(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.omnivoice_runtime.models_dir)
        if selected:
            self.omnivoice_model_id.set(selected)

    def _remove_omnivoice_runtime(self) -> None:
        if not messagebox.askyesno(
            "Gỡ OmniVoice runtime",
            "Gỡ engine, checkpoint và cache? Thư viện giọng sẽ được giữ lại.",
        ):
            return
        self.omnivoice_client.stop()
        try:
            remove_runtime_engine(self.omnivoice_runtime)
        except OSError as error:
            messagebox.showerror("Không gỡ được runtime", str(error))
            return
        self._refresh_omnivoice_runtime_status()
        self._append_omnivoice_log("Đã gỡ runtime; thư viện giọng được giữ nguyên.")

    def _clear_omnivoice_model_cache(self) -> None:
        if not messagebox.askyesno("Xóa model", "Xóa toàn bộ checkpoint và model cache?"):
            return
        self.omnivoice_client.stop()
        try:
            clear_model_cache(self.omnivoice_runtime)
        except OSError as error:
            messagebox.showerror("Không xóa được model", str(error))
            return
        self.omnivoice_worker_status.set("Model chưa nạp")
        self._append_omnivoice_log("Đã xóa checkpoint và model cache.")

    def _refresh_omnivoice_profiles(self) -> None:
        self.omnivoice_profiles = list_voice_profiles(self.omnivoice_runtime.profiles_dir)
        self._omnivoice_profile_by_label = {
            f"{profile.display_name} [{profile.language}]": profile
            for profile in self.omnivoice_profiles
        }
        if self.omnivoice_profile_combos:
            values = ("", *self._omnivoice_profile_by_label)
            for combo in self.omnivoice_profile_combos:
                combo.configure(values=values)
            configured_id = self.omnivoice_profile_choice.get().strip()
            matching = next(
                (
                    label
                    for label, profile in self._omnivoice_profile_by_label.items()
                    if profile.profile_id == configured_id or label == configured_id
                ),
                "",
            )
            self.omnivoice_profile_choice.set(matching)
        if hasattr(self, "omnivoice_profile_tree"):
            self.omnivoice_profile_tree.delete(*self.omnivoice_profile_tree.get_children())
            for profile in self.omnivoice_profiles:
                created = profile.created_at[:19].replace("T", " ")
                self.omnivoice_profile_tree.insert(
                    "",
                    "end",
                    iid=profile.profile_id,
                    values=(profile.display_name, profile.language, created),
                )

    def _selected_omnivoice_profile(self) -> VoiceProfile | None:
        return self._omnivoice_profile_by_label.get(self.omnivoice_profile_choice.get())

    def _omnivoice_config_variables(self) -> tuple[tk.Variable, ...]:
        return (
            self.omnivoice_output_dir,
            self.omnivoice_model_id,
            self.omnivoice_device,
            self.omnivoice_language,
            self.omnivoice_num_step,
            self.omnivoice_guidance_scale,
            self.omnivoice_t_shift,
            self.omnivoice_layer_penalty_factor,
            self.omnivoice_position_temperature,
            self.omnivoice_class_temperature,
            self.omnivoice_speed,
            self.omnivoice_duration,
            self.omnivoice_denoise,
            self.omnivoice_normalize_text,
            self.omnivoice_preprocess_prompt,
            self.omnivoice_postprocess_output,
            self.omnivoice_audio_chunk_duration,
            self.omnivoice_audio_chunk_threshold,
            self.omnivoice_pad_duration,
            self.omnivoice_fade_duration,
            self.omnivoice_export_mp3,
            self.omnivoice_enable_flashinfer,
            self.omnivoice_flashinfer_cuda_graph,
            self.omnivoice_lora_adapter,
            self.omnivoice_profile_choice,
            self.omnivoice_clone_instruct,
            self.omnivoice_batch_mode,
            self.omnivoice_long_form_mode,
            self.omnivoice_long_form_gap_ms,
            self.omnivoice_design_gender,
            self.omnivoice_design_age,
            self.omnivoice_design_pitch,
            self.omnivoice_design_style,
            self.omnivoice_design_accent,
            self.omnivoice_design_dialect,
        )

    def _omnivoice_config_values(self) -> dict[str, object]:
        selected_profile = self._selected_omnivoice_profile()
        return {
            "omnivoice_output_dir": self.omnivoice_output_dir.get().strip(),
            "omnivoice_model_id": self.omnivoice_model_id.get().strip(),
            "omnivoice_device": normalize_omnivoice_device(self.omnivoice_device.get()),
            "omnivoice_language": self.omnivoice_language.get().strip() or "vi",
            "omnivoice_num_step": max(
                4, min(64, self._safe_int(self.omnivoice_num_step, 32))
            ),
            "omnivoice_guidance_scale": self._bounded_float(
                self.omnivoice_guidance_scale, 2.0, 0.0, 4.0
            ),
            "omnivoice_t_shift": self._bounded_float(
                self.omnivoice_t_shift, 0.1, 0.01, 1.0
            ),
            "omnivoice_layer_penalty_factor": self._bounded_float(
                self.omnivoice_layer_penalty_factor, 5.0, 0.0, 20.0
            ),
            "omnivoice_position_temperature": self._bounded_float(
                self.omnivoice_position_temperature, 5.0, 0.0, 20.0
            ),
            "omnivoice_class_temperature": self._bounded_float(
                self.omnivoice_class_temperature, 0.0, 0.0, 5.0
            ),
            "omnivoice_speed": self._bounded_float(
                self.omnivoice_speed, 1.0, 0.5, 1.5
            ),
            "omnivoice_duration": self._bounded_float(
                self.omnivoice_duration, 0.0, 0.0, 600.0
            ),
            "omnivoice_denoise": bool(self.omnivoice_denoise.get()),
            "omnivoice_normalize_text": bool(self.omnivoice_normalize_text.get()),
            "omnivoice_preprocess_prompt": bool(self.omnivoice_preprocess_prompt.get()),
            "omnivoice_postprocess_output": bool(
                self.omnivoice_postprocess_output.get()
            ),
            "omnivoice_audio_chunk_duration": self._bounded_float(
                self.omnivoice_audio_chunk_duration, 15.0, 0.0, 120.0
            ),
            "omnivoice_audio_chunk_threshold": self._bounded_float(
                self.omnivoice_audio_chunk_threshold, 30.0, 0.0, 600.0
            ),
            "omnivoice_pad_duration": self._bounded_float(
                self.omnivoice_pad_duration, 0.0, 0.0, 5.0
            ),
            "omnivoice_fade_duration": self._bounded_float(
                self.omnivoice_fade_duration, 0.02, 0.0, 5.0
            ),
            "omnivoice_export_mp3": bool(self.omnivoice_export_mp3.get()),
            "omnivoice_enable_flashinfer": bool(self.omnivoice_enable_flashinfer.get()),
            "omnivoice_flashinfer_cuda_graph": bool(
                self.omnivoice_flashinfer_cuda_graph.get()
            ),
            "omnivoice_lora_adapter": self.omnivoice_lora_adapter.get().strip(),
            "omnivoice_profile_id": (
                selected_profile.profile_id if selected_profile is not None else ""
            ),
            "omnivoice_clone_instruct": self.omnivoice_clone_instruct.get().strip(),
            "omnivoice_batch_mode": MODE_LABELS.get(
                self.omnivoice_batch_mode.get(), AUTO_MODE
            ),
            "omnivoice_long_form_mode": MODE_LABELS.get(
                self.omnivoice_long_form_mode.get(), AUTO_MODE
            ),
            "omnivoice_long_form_gap_ms": max(
                0, min(5_000, self._safe_int(self.omnivoice_long_form_gap_ms, 250))
            ),
            "omnivoice_design_gender": GENDER_CHOICES.get(
                self.omnivoice_design_gender.get(), ""
            ),
            "omnivoice_design_age": AGE_CHOICES.get(
                self.omnivoice_design_age.get(), ""
            ),
            "omnivoice_design_pitch": PITCH_CHOICES.get(
                self.omnivoice_design_pitch.get(), ""
            ),
            "omnivoice_design_style": STYLE_CHOICES.get(
                self.omnivoice_design_style.get(), ""
            ),
            "omnivoice_design_accent": ACCENT_CHOICES.get(
                self.omnivoice_design_accent.get(), ""
            ),
            "omnivoice_design_dialect": DIALECT_CHOICES.get(
                self.omnivoice_design_dialect.get(), ""
            ),
        }

    def _selected_library_profile(self) -> VoiceProfile | None:
        selection = self.omnivoice_profile_tree.selection()
        if not selection:
            return None
        selected_id = selection[0]
        return next(
            (profile for profile in self.omnivoice_profiles if profile.profile_id == selected_id),
            None,
        )

    def _show_selected_profile(self, _event: tk.Event | None = None) -> None:
        profile = self._selected_library_profile()
        if profile is None:
            return
        lines = [
            f"Tên: {profile.display_name}",
            f"ID: {profile.profile_id}",
            f"Ngôn ngữ: {profile.language}",
            f"Ngày tạo: {profile.created_at}",
            f"Prompt: {profile.prompt_path}",
            f"Audio mẫu: {profile.reference_audio_path or 'Không lưu'}",
            "",
            "Transcript:",
            profile.reference_text or "Không có transcript",
        ]
        self.omnivoice_profile_details.configure(state="normal")
        self.omnivoice_profile_details.delete("1.0", "end")
        self.omnivoice_profile_details.insert("1.0", "\n".join(lines))
        self.omnivoice_profile_details.configure(state="disabled")

    def _use_selected_profile(self) -> None:
        profile = self._selected_library_profile()
        if profile is None:
            return
        label = next(
            label
            for label, candidate in self._omnivoice_profile_by_label.items()
            if candidate.profile_id == profile.profile_id
        )
        self.omnivoice_profile_choice.set(label)
        self.voice_feature_notebook.select(self.omnivoice_clone_tab)

    def _delete_selected_profile(self) -> None:
        profile = self._selected_library_profile()
        if profile is None:
            return
        if not messagebox.askyesno("Xóa profile", f"Xóa profile '{profile.display_name}'?"):
            return
        delete_voice_profile(self.omnivoice_runtime.profiles_dir, profile.profile_id)
        self._refresh_omnivoice_profiles()

    def _play_selected_profile_reference(self) -> None:
        profile = self._selected_library_profile()
        if profile is None or profile.reference_audio_path is None:
            messagebox.showinfo("Không có audio mẫu", "Profile này không lưu audio tham chiếu.")
            return
        os.startfile(profile.reference_audio_path)

    def _omnivoice_design_instruction(self) -> str:
        values = (
            GENDER_CHOICES.get(self.omnivoice_design_gender.get(), ""),
            AGE_CHOICES.get(self.omnivoice_design_age.get(), ""),
            PITCH_CHOICES.get(self.omnivoice_design_pitch.get(), ""),
            STYLE_CHOICES.get(self.omnivoice_design_style.get(), ""),
            ACCENT_CHOICES.get(self.omnivoice_design_accent.get(), ""),
            DIALECT_CHOICES.get(self.omnivoice_design_dialect.get(), ""),
        )
        custom = self.omnivoice_custom_instruct.get("1.0", "end").strip()
        return ", ".join(value for value in (*values, custom) if value)

    def _browse_omnivoice_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.omnivoice_output_dir.get() or None)
        if selected:
            self.omnivoice_output_dir.set(selected)

    def _browse_omnivoice_reference(self) -> None:
        selected = filedialog.askopenfilename(
            filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg"), ("All files", "*.*")]
        )
        if selected:
            self.omnivoice_reference_audio.set(selected)

    def _open_omnivoice_output(self) -> None:
        if self.omnivoice_last_result is not None:
            os.startfile(self.omnivoice_last_result.project_dir)
        elif self.omnivoice_last_batch_result is not None:
            os.startfile(self.omnivoice_last_batch_result.project_dir)
        else:
            self._open_omnivoice_workspace_result()

    def _play_omnivoice_result(self) -> None:
        if self.omnivoice_last_result is not None:
            os.startfile(self.omnivoice_last_result.wav_path)
        elif self.omnivoice_last_batch_result is not None:
            preview = self.omnivoice_last_batch_result.preview_path
            if preview is not None:
                os.startfile(preview)
        else:
            self._play_omnivoice_workspace_result()

    def _open_omnivoice_profiles(self) -> None:
        self.omnivoice_runtime.ensure_directories()
        os.startfile(self.omnivoice_runtime.profiles_dir)

    def _open_omnivoice_runtime(self) -> None:
        self.omnivoice_runtime.ensure_directories()
        os.startfile(self.omnivoice_runtime.root)

    def _append_omnivoice_log(self, message: str) -> None:
        if hasattr(self, "omnivoice_log_text"):
            self.omnivoice_log_text.configure(state="normal")
            self.omnivoice_log_text.insert("end", f"{message}\n")
            self.omnivoice_log_text.see("end")
            self.omnivoice_log_text.configure(state="disabled")
        self._append_log(f"OmniVoice: {message}")

    @staticmethod
    def _safe_int(variable: tk.Variable, default: int) -> int:
        try:
            return int(variable.get())
        except (tk.TclError, TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(variable: tk.Variable, default: float) -> float:
        try:
            return float(variable.get())
        except (tk.TclError, TypeError, ValueError):
            return default

    @classmethod
    def _bounded_float(
        cls,
        variable: tk.Variable,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        value = cls._safe_float(variable, default)
        if not math.isfinite(value):
            value = default
        return max(minimum, min(maximum, value))


def _label_for_value(choices: dict[str, str], value: str) -> str:
    return next((label for label, code in choices.items() if code == value), next(iter(choices)))
