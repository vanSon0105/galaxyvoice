from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from .runtime import (
    VoiceStudioRuntime,
    VoiceStudioRuntimeStatus,
    inspect_runtime,
    load_webview_class,
)
from .service import VoiceStudioController


class VoiceStudioTabMixin:
    def _init_voicestudio_state(self) -> None:
        self.voicestudio_runtime = VoiceStudioRuntime.from_repository()
        self.voicestudio_controller = VoiceStudioController(self.voicestudio_runtime)
        self.voicestudio_status = tk.StringVar(value="Đang kiểm tra VoiceStudio...")
        self.voicestudio_version = tk.StringVar(value="VoiceStudio --")
        self.voicestudio_runtime_detail = tk.StringVar(value="Runtime local chưa được cài")
        self.voicestudio_webview: Any | None = None
        self._voicestudio_launching = False
        self._voicestudio_installing = False
        self._voicestudio_launch_cancelled = False
        self._voicestudio_install_cancelled = False

    def _build_voicestudio_tab(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=4)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        notebook.add(page, text="VoiceStudio")
        notebook.insert(0, page)
        self.voicestudio_tab = page

        toolbar = ttk.Frame(page, padding=(8, 6))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, textvariable=self.voicestudio_version, style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        ttk.Label(toolbar, textvariable=self.voicestudio_status).grid(
            row=0, column=1, sticky="w"
        )
        self.voicestudio_install_button = ttk.Button(
            toolbar,
            text="Cài runtime local",
            command=self._install_voicestudio,
        )
        self.voicestudio_install_button.grid(row=0, column=2, padx=3)
        self.voicestudio_launch_button = ttk.Button(
            toolbar,
            text="Khởi động",
            style="Accent.TButton",
            command=self._launch_voicestudio,
        )
        self.voicestudio_launch_button.grid(row=0, column=3, padx=3)
        self.voicestudio_reload_button = ttk.Button(
            toolbar,
            text="Tải lại",
            command=self._reload_voicestudio,
            state="disabled",
        )
        self.voicestudio_reload_button.grid(row=0, column=4, padx=3)
        self.voicestudio_browser_button = ttk.Button(
            toolbar,
            text="Mở trình duyệt",
            command=self._open_voicestudio_browser,
            state="disabled",
        )
        self.voicestudio_browser_button.grid(row=0, column=5, padx=3)
        self.voicestudio_stop_button = ttk.Button(
            toolbar,
            text="Dừng",
            command=self._stop_voicestudio,
            state="disabled",
        )
        self.voicestudio_stop_button.grid(row=0, column=6, padx=(3, 0))

        content = ttk.Frame(page)
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        self.voicestudio_content = content

        self.voicestudio_bootstrap = ttk.Frame(content, padding=24)
        self.voicestudio_bootstrap.grid(row=0, column=0, sticky="nsew")
        self.voicestudio_bootstrap.columnconfigure(0, weight=1)
        self.voicestudio_bootstrap.rowconfigure(0, weight=1)
        setup = ttk.Frame(self.voicestudio_bootstrap)
        setup.grid(row=0, column=0)
        ttk.Label(setup, text="VoiceStudio local", style="Header.TLabel").grid(
            row=0, column=0, pady=(0, 10)
        )
        ttk.Label(
            setup,
            textvariable=self.voicestudio_runtime_detail,
            justify="center",
            wraplength=760,
        ).grid(row=1, column=0, pady=(0, 14))
        ttk.Button(
            setup,
            text="Cài runtime local",
            style="Accent.TButton",
            command=self._install_voicestudio,
        ).grid(row=2, column=0)

        self.voicestudio_webview_host = tk.Frame(
            content,
            background="#0a0d10",
            width=960,
            height=620,
        )
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
        if self._voicestudio_launching:
            return
        status = inspect_runtime(self.voicestudio_runtime, probe_backend=False)
        if not status.installed:
            messagebox.showinfo(
                "VoiceStudio chưa sẵn sàng",
                "Hãy cài runtime local trước. Snapshot đã nằm sẵn trong Galaxy; "
                "bộ cài chỉ tải các dependency Python cần thiết.",
            )
            return
        self._voicestudio_launching = True
        self._voicestudio_launch_cancelled = False
        self.voicestudio_status.set("Đang khởi động backend VoiceStudio...")
        self._update_voicestudio_buttons(status)
        threading.Thread(
            target=self._launch_voicestudio_worker,
            name="voicestudio-launch",
            daemon=True,
        ).start()

    def _launch_voicestudio_worker(self) -> None:
        try:
            mode = self.voicestudio_controller.launch()
            if not self.voicestudio_controller.wait_until_ready():
                detail = self.voicestudio_controller.backend_log_tail()
                suffix = f"\n\nLog cuối:\n{detail}" if detail else ""
                raise RuntimeError(
                    "Backend VoiceStudio đã dừng hoặc không sẵn sàng sau 4 phút." + suffix
                )
            self.events.put(("voicestudio_launched", mode))
        except Exception as error:
            self.events.put(("voicestudio_error", error))

    def _install_voicestudio(self) -> None:
        if self._voicestudio_installing:
            return
        if not messagebox.askyesno(
            "Cài VoiceStudio local",
            "Cài snapshot VoiceStudio đi kèm Galaxy và các dependency Python?\n\n"
            "Quá trình đầu tiên có thể tải vài GB. Có thể dừng bằng nút Dừng hoặc Ctrl+C "
            "trong cửa sổ cài đặt.",
        ):
            return
        try:
            process = self.voicestudio_controller.run_installer()
        except Exception as error:
            messagebox.showerror("Không thể cài VoiceStudio", str(error))
            return
        self._voicestudio_installing = True
        self._voicestudio_install_cancelled = False
        self.voicestudio_status.set("Đang cài runtime local...")
        self.voicestudio_stop_button.configure(state="normal")
        self.voicestudio_install_button.configure(state="disabled")
        self._append_log("Đang cài VoiceStudio từ snapshot local của Galaxy.")
        threading.Thread(
            target=self._wait_for_voicestudio_installer,
            args=(process,),
            name="voicestudio-installer",
            daemon=True,
        ).start()

    def _wait_for_voicestudio_installer(self, process: Any) -> None:
        return_code = process.wait()
        self.voicestudio_controller.finish_installer(process)
        self.events.put(("voicestudio_installed", return_code))

    def _mount_voicestudio_webview(self) -> None:
        if self.voicestudio_webview is not None:
            self.voicestudio_webview.reload()
            return
        self.voicestudio_runtime.ensure_directories()
        webview_class = load_webview_class(self.voicestudio_runtime)
        self.voicestudio_bootstrap.grid_remove()
        self.voicestudio_webview_host.grid(row=0, column=0, sticky="nsew")
        self.voicestudio_webview_host.update_idletasks()
        try:
            self.voicestudio_webview = webview_class(
                self.voicestudio_webview_host,
                url=self.voicestudio_runtime.backend_url,
                data_directory=self.voicestudio_runtime.webview_data_dir,
                open_external=True,
                background_color=(10, 13, 16, 255),
                on_creation_failed=lambda error: self.events.put(
                    ("voicestudio_webview_failed", error)
                ),
            )
        except Exception:
            self.voicestudio_webview_host.grid_remove()
            self.voicestudio_bootstrap.grid(row=0, column=0, sticky="nsew")
            raise

    def _destroy_voicestudio_webview(self) -> None:
        webview = self.voicestudio_webview
        self.voicestudio_webview = None
        if webview is not None:
            try:
                webview.destroy()
            except Exception as error:
                self._append_log(f"VoiceStudio WebView cleanup: {error}")
        try:
            self.voicestudio_webview_host.grid_remove()
            self.voicestudio_bootstrap.grid(row=0, column=0, sticky="nsew")
        except tk.TclError:
            pass

    def _reload_voicestudio(self) -> None:
        if self.voicestudio_webview is None:
            self._launch_voicestudio()
            return
        try:
            self.voicestudio_webview.reload()
            self.voicestudio_status.set("Đã tải lại VoiceStudio")
        except Exception as error:
            messagebox.showerror("VoiceStudio", str(error))

    def _open_voicestudio_browser(self) -> None:
        try:
            self.voicestudio_controller.open_browser()
        except Exception as error:
            messagebox.showerror("VoiceStudio", str(error))

    def _stop_voicestudio(self) -> None:
        was_installing = self.voicestudio_controller.installer_running()
        self._voicestudio_install_cancelled = was_installing
        self._voicestudio_launch_cancelled = self._voicestudio_launching
        self._destroy_voicestudio_webview()
        self.voicestudio_controller.stop_all()
        self._voicestudio_launching = False
        self._voicestudio_installing = False
        self.voicestudio_status.set(
            "Đã dừng cài đặt VoiceStudio" if was_installing else "Đã dừng VoiceStudio"
        )
        self._refresh_voicestudio_status()

    def _handle_voicestudio_event(self, event: str, payload: object) -> bool:
        if event == "voicestudio_status" and isinstance(payload, VoiceStudioRuntimeStatus):
            self._apply_voicestudio_status(payload)
            return True
        if event == "voicestudio_launched":
            self._voicestudio_launching = False
            if self._voicestudio_launch_cancelled:
                self._voicestudio_launch_cancelled = False
                return True
            try:
                self._mount_voicestudio_webview()
            except Exception as error:
                self.voicestudio_status.set("Không thể nhúng giao diện VoiceStudio")
                self._append_log(f"VoiceStudio WebView error: {error}")
                messagebox.showerror("VoiceStudio WebView", str(error))
                return True
            self.voicestudio_status.set("VoiceStudio đang chạy trong Galaxy")
            self.voicestudio_reload_button.configure(state="normal")
            self.voicestudio_browser_button.configure(state="normal")
            self.voicestudio_stop_button.configure(state="normal")
            self._append_log(f"VoiceStudio local launch mode: {payload}")
            return True
        if event == "voicestudio_installed":
            self._voicestudio_installing = False
            return_code = int(payload)
            if self._voicestudio_install_cancelled:
                self._voicestudio_install_cancelled = False
                self.voicestudio_status.set("Đã dừng cài đặt VoiceStudio")
                self._refresh_voicestudio_status()
                return True
            if return_code == 0:
                self.voicestudio_status.set("Cài runtime local hoàn tất")
                self._append_log("VoiceStudio local runtime installed.")
                self._refresh_voicestudio_status()
            else:
                self.voicestudio_status.set("Cài runtime local chưa hoàn tất")
                messagebox.showerror(
                    "Cài VoiceStudio thất bại",
                    f"Bộ cài đã dừng với mã {return_code}. Bấm Cài runtime local để tiếp tục.",
                )
                self._refresh_voicestudio_status()
            return True
        if event == "voicestudio_webview_failed":
            self._destroy_voicestudio_webview()
            self.voicestudio_status.set("WebView2 không khởi tạo được")
            self._append_log(f"VoiceStudio WebView creation failed: {payload}")
            messagebox.showerror(
                "VoiceStudio WebView",
                f"Không thể nhúng giao diện: {payload}\n\n"
                "Backend vẫn chạy; có thể dùng nút Mở trình duyệt.",
            )
            return True
        if event == "voicestudio_error":
            self._voicestudio_launching = False
            if self._voicestudio_launch_cancelled:
                self._voicestudio_launch_cancelled = False
                return True
            self.voicestudio_status.set("Không thể khởi động VoiceStudio")
            self._append_log(f"VoiceStudio error: {payload}")
            messagebox.showerror("VoiceStudio", str(payload))
            self._refresh_voicestudio_status()
            return True
        return False

    def _apply_voicestudio_status(self, status: VoiceStudioRuntimeStatus) -> None:
        self.voicestudio_status.set(status.message)
        self.voicestudio_version.set(f"VoiceStudio {status.version}")
        if status.installed:
            self.voicestudio_runtime_detail.set(
                f"Runtime local: {status.python_path}\n"
                f"Dữ liệu và model: {self.voicestudio_runtime.data_dir}"
            )
        else:
            detail = ", ".join(status.missing_components) or "runtime cần cập nhật"
            self.voicestudio_runtime_detail.set(
                f"Snapshot đã đóng gói: {status.source_dir.name}\nCần cài: {detail}"
            )
        self._update_voicestudio_buttons(status)

    def _update_voicestudio_buttons(self, status: VoiceStudioRuntimeStatus) -> None:
        installing = self._voicestudio_installing or self.voicestudio_controller.installer_running()
        running = status.backend_online or self.voicestudio_controller.is_running()
        self.voicestudio_install_button.configure(
            state="normal" if status.snapshot_present and not installing else "disabled",
            text="Cập nhật runtime" if status.update_required else "Cài runtime local",
        )
        self.voicestudio_launch_button.configure(
            state=(
                "normal"
                if status.installed and not installing and not self._voicestudio_launching
                else "disabled"
            )
        )
        self.voicestudio_reload_button.configure(
            state="normal" if self.voicestudio_webview is not None else "disabled"
        )
        self.voicestudio_browser_button.configure(state="normal" if running else "disabled")
        self.voicestudio_stop_button.configure(
            state="normal" if running or installing or self._voicestudio_launching else "disabled"
        )
