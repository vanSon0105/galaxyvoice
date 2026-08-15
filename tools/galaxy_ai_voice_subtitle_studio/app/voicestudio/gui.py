from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .runtime import VoiceStudioRuntime, VoiceStudioRuntimeStatus, inspect_runtime
from .service import VoiceStudioController


WORKSPACES = (
    "Studio",
    "Dubbing",
    "Stories",
    "Audiobook",
    "Gallery",
    "Transcriptions",
    "Projects",
    "Settings",
)


class VoiceStudioTabMixin:
    def _init_voicestudio_state(self) -> None:
        self.voicestudio_runtime = VoiceStudioRuntime.from_repository()
        self.voicestudio_controller = VoiceStudioController(self.voicestudio_runtime)
        self.voicestudio_status = tk.StringVar(value="Đang kiểm tra VoiceStudio...")
        self.voicestudio_version = tk.StringVar(value="Version --")
        self.voicestudio_backend = tk.StringVar(value="Backend: chưa chạy")
        self.voicestudio_installation = tk.StringVar(value="Desktop: chưa cài")

    def _build_voicestudio_tab(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=12)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        notebook.add(page, text="VoiceStudio")
        notebook.insert(0, page)
        self.voicestudio_tab = page

        header = ttk.Frame(page)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="VoiceStudio", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.voicestudio_version).grid(row=0, column=1, sticky="e")
        ttk.Label(header, textvariable=self.voicestudio_status).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        actions = ttk.Frame(page, style="Panel.TFrame", padding=12)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for column in range(5):
            actions.columnconfigure(column, weight=1)
        self.voicestudio_launch_button = ttk.Button(
            actions,
            text="Mở VoiceStudio",
            style="Accent.TButton",
            command=self._launch_voicestudio,
        )
        self.voicestudio_launch_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Cài bản đầy đủ", command=self._install_voicestudio).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        self.voicestudio_source_button = ttk.Button(
            actions,
            text="Chạy source",
            command=self._launch_voicestudio_source,
        )
        self.voicestudio_source_button.grid(row=0, column=2, sticky="ew", padx=6)
        self.voicestudio_stop_button = ttk.Button(
            actions,
            text="Dừng",
            command=self._stop_voicestudio,
            state="disabled",
        )
        self.voicestudio_stop_button.grid(row=0, column=3, sticky="ew", padx=6)
        ttk.Button(actions, text="Làm mới", command=self._refresh_voicestudio_status).grid(
            row=0, column=4, sticky="ew", padx=(6, 0)
        )

        body = ttk.Frame(page)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        workspace_panel = ttk.Frame(body, style="Panel.TFrame", padding=12)
        workspace_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        workspace_panel.columnconfigure(0, weight=1)
        ttk.Label(workspace_panel, text="Workspaces", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.voicestudio_workspace_tree = ttk.Treeview(
            workspace_panel,
            columns=("workspace",),
            show="headings",
            selectmode="browse",
            height=len(WORKSPACES),
        )
        self.voicestudio_workspace_tree.heading("workspace", text="VoiceStudio")
        self.voicestudio_workspace_tree.column("workspace", anchor="w", stretch=True)
        for workspace in WORKSPACES:
            self.voicestudio_workspace_tree.insert("", "end", values=(workspace,))
        self.voicestudio_workspace_tree.grid(row=1, column=0, sticky="nsew")
        self.voicestudio_workspace_tree.bind("<Double-1>", lambda _event: self._launch_voicestudio())
        workspace_panel.rowconfigure(1, weight=1)

        status_panel = ttk.Frame(body, style="Panel.TFrame", padding=12)
        status_panel.grid(row=0, column=1, sticky="nsew")
        status_panel.columnconfigure(0, weight=1)
        ttk.Label(status_panel, text="Runtime", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(status_panel, textvariable=self.voicestudio_installation, style="Panel.TLabel").grid(
            row=1, column=0, sticky="w", pady=3
        )
        ttk.Label(status_panel, textvariable=self.voicestudio_backend, style="Panel.TLabel").grid(
            row=2, column=0, sticky="w", pady=3
        )
        ttk.Label(
            status_panel,
            text=f"Source: {self.voicestudio_runtime.source_dir}",
            style="Panel.TLabel",
            wraplength=760,
        ).grid(row=3, column=0, sticky="w", pady=3)
        ttk.Label(
            status_panel,
            text="License: AGPL-3.0-only (VoiceStudio chạy như ứng dụng riêng)",
            style="Panel.TLabel",
        ).grid(row=4, column=0, sticky="w", pady=3)
        self._apply_voicestudio_status(
            inspect_runtime(self.voicestudio_runtime, probe_backend=False)
        )

    def _refresh_voicestudio_status(self) -> None:
        self.voicestudio_status.set("Đang kiểm tra VoiceStudio...")
        threading.Thread(
            target=self._inspect_voicestudio_worker,
            name="voicestudio-status",
            daemon=True,
        ).start()

    def _inspect_voicestudio_worker(self) -> None:
        try:
            self.events.put(("voicestudio_status", inspect_runtime(self.voicestudio_runtime)))
        except Exception as error:
            self.events.put(("voicestudio_error", error))

    def _launch_voicestudio(self) -> None:
        self.voicestudio_status.set("Đang mở VoiceStudio...")
        threading.Thread(
            target=self._launch_voicestudio_worker,
            args=(False,),
            name="voicestudio-launch",
            daemon=True,
        ).start()

    def _launch_voicestudio_source(self) -> None:
        self.voicestudio_status.set("Đang chạy VoiceStudio từ source...")
        threading.Thread(
            target=self._launch_voicestudio_worker,
            args=(True,),
            name="voicestudio-source-launch",
            daemon=True,
        ).start()

    def _launch_voicestudio_worker(self, source: bool) -> None:
        try:
            mode = (
                self.voicestudio_controller.launch_source()
                if source
                else self.voicestudio_controller.launch()
            )
            if mode == "source":
                if not self.voicestudio_controller.wait_for_source_ready():
                    raise RuntimeError(
                        "VoiceStudio source đã dừng hoặc chưa sẵn sàng sau 15 phút. Kiểm tra cửa sổ runtime."
                    )
                self.voicestudio_controller.open_browser()
            self.events.put(("voicestudio_launched", mode))
        except Exception as error:
            self.events.put(("voicestudio_error", error))

    def _install_voicestudio(self) -> None:
        try:
            self.voicestudio_controller.run_installer()
        except Exception as error:
            messagebox.showerror("Không thể cài VoiceStudio", str(error))
            return
        self.voicestudio_status.set("Đã mở bộ cài VoiceStudio")
        self._append_log("Đã mở bộ cài VoiceStudio chính thức.")

    def _stop_voicestudio(self) -> None:
        self.voicestudio_controller.stop()
        self.voicestudio_stop_button.configure(state="disabled")
        self.voicestudio_status.set("Đã dừng VoiceStudio do Galaxy khởi chạy")
        self._refresh_voicestudio_status()

    def _handle_voicestudio_event(self, event: str, payload: object) -> bool:
        if event == "voicestudio_status" and isinstance(payload, VoiceStudioRuntimeStatus):
            self._apply_voicestudio_status(payload)
            return True
        if event == "voicestudio_launched":
            mode = str(payload)
            self.voicestudio_status.set(
                "VoiceStudio đang chạy" if mode != "browser" else "Đã mở VoiceStudio trên trình duyệt"
            )
            self.voicestudio_stop_button.configure(
                state="normal" if self.voicestudio_controller.is_running() else "disabled"
            )
            self._append_log(f"VoiceStudio launch mode: {mode}")
            return True
        if event == "voicestudio_error":
            self.voicestudio_status.set("Không thể mở VoiceStudio")
            self._append_log(f"VoiceStudio error: {payload}")
            messagebox.showerror("VoiceStudio", str(payload))
            return True
        return False

    def _apply_voicestudio_status(self, status: VoiceStudioRuntimeStatus) -> None:
        self.voicestudio_status.set(status.message)
        self.voicestudio_version.set(f"Version {status.version}")
        self.voicestudio_installation.set(
            f"Desktop: {status.executable}" if status.executable else "Desktop: chưa cài"
        )
        self.voicestudio_backend.set(
            "Backend: đang chạy" if status.backend_online else "Backend: chưa chạy"
        )
        self.voicestudio_source_button.configure(state="normal" if status.source_ready else "disabled")
        self.voicestudio_stop_button.configure(
            state="normal" if self.voicestudio_controller.is_running() else "disabled"
        )
