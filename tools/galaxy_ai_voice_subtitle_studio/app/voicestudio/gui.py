from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from ..common.theme import PALETTE
from .runtime import (
    WebViewProfileLease,
    VoiceStudioRuntime,
    VoiceStudioRuntimeStatus,
    acquire_webview_profile,
    inspect_runtime,
    load_webview_class,
)
from .service import VoiceStudioController


VOICESTUDIO_THEME_SCRIPT = r"""
(() => {
  const tokens = {
    "--color-fg": "#f4f1ea",
    "--color-fg-muted": "#c3c0b9",
    "--color-fg-subtle": "#9da2a8",
    "--color-fg-inverse": "#171214",
    "--color-bg": "#111315",
    "--color-bg-elev-1": "#191c1f",
    "--color-bg-elev-2": "#15181b",
    "--color-bg-elev-3": "#23272b",
    "--color-border": "rgba(255, 255, 255, 0.12)",
    "--color-border-strong": "rgba(255, 255, 255, 0.23)",
    "--color-border-warm": "rgba(208, 140, 161, 0.20)",
    "--color-brand": "#d08ca1",
    "--color-brand-hover": "#e09bb0",
    "--color-brand-glow": "rgba(208, 140, 161, 0.36)",
    "--color-chrome-bg": "#0c0f11",
    "--color-chrome-fg": "#e5e1d9",
    "--bg": "#111315",
    "--glass-bg": "rgba(25, 28, 31, 0.96)",
    "--glass-border": "rgba(255, 255, 255, 0.12)",
    "--text-primary": "#f4f1ea",
    "--text-secondary": "#c3c0b9",
    "--chrome-bg": "#0c0f11",
    "--chrome-border": "rgba(255, 255, 255, 0.12)",
    "--chrome-border-strong": "rgba(255, 255, 255, 0.23)",
    "--chrome-fg": "#e5e1d9",
    "--chrome-fg-muted": "#bbb8b1",
    "--chrome-fg-dim": "#979ca2",
    "--chrome-hover-bg": "rgba(255, 255, 255, 0.08)",
    "--text-2xs": "0.68rem",
    "--text-xs": "0.72rem",
    "--text-sm": "0.78rem",
    "--text-base": "0.84rem",
    "--text-md": "0.90rem",
    "--text-lg": "1rem",
    "--text-xl": "1.12rem",
    "--text-2xl": "1.48rem",
    "--chrome-label-size": "12px",
    "--chrome-label-track": "0.035em",
    "--font-sans": "'Segoe UI Variable Text', 'Segoe UI', Arial, sans-serif",
    "--font-ui": "'Segoe UI Variable Text', 'Segoe UI', Arial, sans-serif",
    "--font-mono": "'Cascadia Mono', 'Cascadia Code', Consolas, monospace",
    "--chrome-font-mono": "'Cascadia Mono', 'Cascadia Code', Consolas, monospace"
  };

  const applyGalaxyTheme = () => {
    const root = document.documentElement;
    for (const [name, value] of Object.entries(tokens)) {
      root.style.setProperty(name, value, "important");
    }
    root.style.colorScheme = "dark";

    if (document.body) {
      document.body.style.backgroundColor = tokens["--color-bg"];
      document.body.style.color = tokens["--color-fg"];
      document.body.style.fontFamily = tokens["--font-sans"];
      document.body.style.textRendering = "optimizeLegibility";
      document.body.style.webkitFontSmoothing = "antialiased";
    }

    if (document.head && !document.getElementById("galaxy-visual-theme")) {
      const style = document.createElement("style");
      style.id = "galaxy-visual-theme";
      style.textContent = `
        html, body, #root {
          background: #111315 !important;
        }
        body, button, input, select, textarea {
          font-family: 'Segoe UI Variable Text', 'Segoe UI', Arial, sans-serif !important;
          text-rendering: optimizeLegibility;
          -webkit-font-smoothing: antialiased;
        }
        input, select, textarea {
          color: #f4f1ea !important;
        }
        input::placeholder, textarea::placeholder {
          color: #959ba2 !important;
          opacity: 1 !important;
        }
        ::selection {
          color: #f4f1ea;
          background: #70495a;
        }
      `;
      document.head.appendChild(style);
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyGalaxyTheme, { once: true });
  } else {
    applyGalaxyTheme();
  }
  new MutationObserver(applyGalaxyTheme).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"]
  });
})();
"""


class VoiceStudioTabMixin:
    def _init_voicestudio_state(self) -> None:
        self.voicestudio_runtime = VoiceStudioRuntime.from_repository()
        self.voicestudio_controller = VoiceStudioController(self.voicestudio_runtime)
        self.voicestudio_status = tk.StringVar(value="Đang kiểm tra VoiceStudio...")
        self.voicestudio_version = tk.StringVar(value="VoiceStudio --")
        self.voicestudio_bootstrap_title = tk.StringVar(value="VoiceStudio local")
        self.voicestudio_runtime_detail = tk.StringVar(value="Runtime local chưa được cài")
        self.voicestudio_webview: Any | None = None
        self._voicestudio_profile_lease: WebViewProfileLease | None = None
        self._voicestudio_pending_profile_lease: WebViewProfileLease | None = None
        self._voicestudio_profile_lock = threading.Lock()
        self._voicestudio_launching = False
        self._voicestudio_installing = False
        self._voicestudio_launch_cancelled = False
        self._voicestudio_install_cancelled = False
        self._voicestudio_auto_launch_attempted = False
        self._voicestudio_user_stopped = False
        self._voicestudio_launch_failed = False

    def _build_voicestudio_tab(self, notebook: ttk.Notebook) -> None:
        page = ttk.Frame(notebook, padding=4)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        notebook.add(page, text="VoiceStudio")
        notebook.insert(0, page)
        self.voicestudio_tab = page

        toolbar = ttk.Frame(page, style="Toolbar.TFrame", padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, textvariable=self.voicestudio_version, style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        ttk.Label(toolbar, textvariable=self.voicestudio_status, style="Toolbar.TLabel").grid(
            row=0, column=1, sticky="w"
        )
        self.voicestudio_install_button = ttk.Button(
            toolbar,
            text="Cài runtime local",
            style="Accent.TButton",
            command=self._install_voicestudio,
        )
        self.voicestudio_install_button.grid(row=0, column=2, padx=3)
        self.voicestudio_manage_menu = tk.Menu(toolbar, tearoff=False)
        self.voicestudio_manage_menu.add_command(
            label="Thử khởi động lại",
            command=self._retry_voicestudio,
        )
        self.voicestudio_manage_menu.add_command(
            label="Tải lại giao diện",
            command=self._reload_voicestudio,
        )
        self.voicestudio_manage_menu.add_command(
            label="Mở trong trình duyệt",
            command=self._open_voicestudio_browser,
        )
        self.voicestudio_manage_menu.add_separator()
        self.voicestudio_manage_menu.add_command(
            label="Sửa chữa / cập nhật runtime",
            command=self._install_voicestudio,
        )
        self.voicestudio_manage_menu.add_command(
            label="Dừng VoiceStudio",
            command=self._stop_voicestudio,
        )
        self.voicestudio_manage_button = ttk.Menubutton(
            toolbar,
            text="Quản lý",
            menu=self.voicestudio_manage_menu,
        )
        self.voicestudio_manage_button.grid(row=0, column=3, padx=(3, 0))

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
        ttk.Label(
            setup,
            textvariable=self.voicestudio_bootstrap_title,
            style="Header.TLabel",
        ).grid(
            row=0, column=0, pady=(0, 10)
        )
        ttk.Label(
            setup,
            textvariable=self.voicestudio_runtime_detail,
            justify="center",
            wraplength=self._px(760),
        ).grid(row=1, column=0, pady=(0, 14))
        self.voicestudio_bootstrap_progress = ttk.Progressbar(
            setup,
            mode="indeterminate",
            length=self._px(320),
        )
        self.voicestudio_bootstrap_progress.grid(row=2, column=0, pady=(0, 14))
        self.voicestudio_bootstrap_progress.grid_remove()
        self.voicestudio_bootstrap_install_button = ttk.Button(
            setup,
            text="Cài runtime local",
            style="Accent.TButton",
            command=self._install_voicestudio,
        )
        self.voicestudio_bootstrap_install_button.grid(row=3, column=0)
        self.voicestudio_retry_button = ttk.Button(
            setup,
            text="Thử lại",
            style="Accent.TButton",
            command=self._retry_voicestudio,
        )
        self.voicestudio_retry_button.grid(row=3, column=0)
        self.voicestudio_retry_button.grid_remove()

        self.voicestudio_webview_host = tk.Frame(
            content,
            background=PALETTE.preview,
            width=self._px(960),
            height=self._px(620),
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

    def _activate_voicestudio_tab(
        self,
        status: VoiceStudioRuntimeStatus | None = None,
    ) -> None:
        if not self._voicestudio_tab_is_active():
            return
        current = status or inspect_runtime(self.voicestudio_runtime, probe_backend=False)
        if status is None and not self._voicestudio_launch_failed:
            self._apply_voicestudio_status(current)
        if (
            not current.installed
            or self.voicestudio_webview is not None
            or self._voicestudio_launching
            or self._voicestudio_installing
            or self._voicestudio_user_stopped
            or self._voicestudio_auto_launch_attempted
        ):
            return
        self._voicestudio_auto_launch_attempted = True
        self._launch_voicestudio(status=current, automatic=True)

    def _voicestudio_tab_is_active(self) -> bool:
        try:
            return (
                self.main_notebook.select() == str(self.voice_tab)
                and self.voice_feature_notebook.select() == str(self.voicestudio_tab)
            )
        except (AttributeError, tk.TclError):
            return False

    def _retry_voicestudio(self) -> None:
        self._voicestudio_user_stopped = False
        self._voicestudio_launch_failed = False
        self._voicestudio_auto_launch_attempted = True
        self._launch_voicestudio(automatic=False)

    def _show_voicestudio_bootstrap(
        self,
        *,
        title: str,
        detail: str,
        action: str = "none",
        busy: bool = False,
    ) -> None:
        self.voicestudio_bootstrap_title.set(title)
        self.voicestudio_runtime_detail.set(detail)
        self.voicestudio_webview_host.grid_remove()
        self.voicestudio_bootstrap.grid(row=0, column=0, sticky="nsew")
        self.voicestudio_bootstrap_install_button.grid_remove()
        self.voicestudio_retry_button.grid_remove()
        self.voicestudio_bootstrap_progress.stop()
        self.voicestudio_bootstrap_progress.grid_remove()
        if busy:
            self.voicestudio_bootstrap_progress.grid()
            self.voicestudio_bootstrap_progress.start(12)
        elif action == "install":
            self.voicestudio_bootstrap_install_button.grid()
        elif action == "retry":
            self.voicestudio_retry_button.grid()

    def _launch_voicestudio(
        self,
        *,
        status: VoiceStudioRuntimeStatus | None = None,
        automatic: bool = False,
    ) -> None:
        if self._voicestudio_launching:
            return
        current = status or inspect_runtime(self.voicestudio_runtime, probe_backend=False)
        if not current.installed:
            self._apply_voicestudio_status(current)
            if not automatic:
                messagebox.showinfo(
                    "VoiceStudio chưa sẵn sàng",
                    "Hãy cài runtime local trước. Snapshot đã nằm sẵn trong Galaxy; "
                    "bộ cài chỉ tải các dependency Python cần thiết.",
                )
            return
        self._voicestudio_user_stopped = False
        self._voicestudio_launch_failed = False
        self._voicestudio_launching = True
        self._voicestudio_launch_cancelled = False
        self.voicestudio_status.set("Đang khởi động VoiceStudio...")
        self._show_voicestudio_bootstrap(
            title="Đang khởi động VoiceStudio",
            detail=(
                "Galaxy đang nạp dịch vụ giọng nói và giao diện local. "
                "Lần khởi động đầu tiên có thể mất một lúc."
            ),
            busy=True,
        )
        self._update_voicestudio_controls(current)
        threading.Thread(
            target=self._launch_voicestudio_worker,
            name="voicestudio-launch",
            daemon=True,
        ).start()

    def _launch_voicestudio_worker(self) -> None:
        profile_lease: WebViewProfileLease | None = None
        try:
            if self._voicestudio_launch_cancelled:
                return
            mode = self.voicestudio_controller.launch()
            if self._voicestudio_launch_cancelled:
                self.voicestudio_controller.stop()
                return
            if not self.voicestudio_controller.wait_until_ready():
                detail = self.voicestudio_controller.backend_log_tail()
                suffix = f"\n\nLog cuối:\n{detail}" if detail else ""
                raise RuntimeError(
                    "Backend VoiceStudio đã dừng hoặc không sẵn sàng sau 4 phút." + suffix
                )
            if self._voicestudio_launch_cancelled:
                self.voicestudio_controller.stop()
                return
            self.voicestudio_controller.disable_upstream_analytics()
            profile_lease = acquire_webview_profile(self.voicestudio_runtime)
            with self._voicestudio_profile_lock:
                cancelled = self._voicestudio_launch_cancelled
                if not cancelled:
                    self._voicestudio_pending_profile_lease = profile_lease
                    profile_lease = None
            if cancelled:
                if profile_lease is not None:
                    profile_lease.release()
                self.voicestudio_controller.stop()
                return
            self.events.put(("voicestudio_launched", mode))
        except Exception as error:
            if profile_lease is not None:
                profile_lease.release()
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
        self._voicestudio_user_stopped = False
        self.voicestudio_status.set("Đang cài runtime local...")
        self._show_voicestudio_bootstrap(
            title="Đang cài VoiceStudio",
            detail=(
                "Galaxy đang chuẩn bị runtime local. Có thể theo dõi chi tiết "
                "trong cửa sổ cài đặt."
            ),
            busy=True,
        )
        self._update_voicestudio_controls(
            inspect_runtime(self.voicestudio_runtime, probe_backend=False)
        )
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

    def _mount_voicestudio_webview(
        self,
        profile_lease: WebViewProfileLease | None = None,
    ) -> None:
        if self.voicestudio_webview is not None:
            if profile_lease is not None:
                profile_lease.release()
            self.voicestudio_webview.reload()
            return
        self.voicestudio_runtime.ensure_directories()
        profile_lease = profile_lease or acquire_webview_profile(self.voicestudio_runtime)
        self._voicestudio_profile_lease = profile_lease
        if profile_lease.recovered:
            self._append_log(
                "VoiceStudio dùng profile WebView2 khôi phục vì phiên trước chưa thoát sạch."
            )
        try:
            webview_class = load_webview_class(self.voicestudio_runtime)
            self.voicestudio_bootstrap.grid_remove()
            self.voicestudio_webview_host.grid(row=0, column=0, sticky="nsew")
            self.voicestudio_webview_host.update_idletasks()
            self.voicestudio_webview = webview_class(
                self.voicestudio_webview_host,
                url=self.voicestudio_runtime.backend_url,
                data_directory=profile_lease.data_directory,
                open_external=True,
                background_color=(12, 15, 17, 255),
                initialization_script=VOICESTUDIO_THEME_SCRIPT,
                on_creation_failed=lambda error: self.events.put(
                    ("voicestudio_webview_failed", error)
                ),
            )
        except Exception:
            self.voicestudio_webview_host.grid_remove()
            self.voicestudio_bootstrap.grid(row=0, column=0, sticky="nsew")
            self._release_voicestudio_profile()
            raise

    def _release_voicestudio_profile(self) -> None:
        lease = self._voicestudio_profile_lease
        self._voicestudio_profile_lease = None
        if lease is not None:
            lease.release()

    def _take_pending_voicestudio_profile(self) -> WebViewProfileLease | None:
        with self._voicestudio_profile_lock:
            lease = self._voicestudio_pending_profile_lease
            self._voicestudio_pending_profile_lease = None
        return lease

    def _release_pending_voicestudio_profile(self) -> None:
        lease = self._take_pending_voicestudio_profile()
        if lease is not None:
            lease.release()

    def _destroy_voicestudio_webview(self) -> None:
        self._release_pending_voicestudio_profile()
        webview = self.voicestudio_webview
        self.voicestudio_webview = None
        if webview is not None:
            try:
                webview.destroy()
            except Exception as error:
                self._append_log(f"VoiceStudio WebView cleanup: {error}")
        self._release_voicestudio_profile()
        try:
            self.voicestudio_webview_host.grid_remove()
            self.voicestudio_bootstrap.grid(row=0, column=0, sticky="nsew")
        except tk.TclError:
            pass

    def _reload_voicestudio(self) -> None:
        if self.voicestudio_webview is None:
            self._retry_voicestudio()
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
        self._voicestudio_user_stopped = True
        self._voicestudio_launch_failed = False
        self._voicestudio_auto_launch_attempted = True
        self._destroy_voicestudio_webview()
        self.voicestudio_controller.stop_all()
        self._voicestudio_launching = False
        self._voicestudio_installing = False
        stopped_message = (
            "Đã dừng cài đặt VoiceStudio" if was_installing else "Đã dừng VoiceStudio"
        )
        self.voicestudio_status.set(stopped_message)
        self._show_voicestudio_bootstrap(
            title=stopped_message,
            detail="Chọn Thử lại để khởi động VoiceStudio khi cần.",
            action="retry",
        )
        self._update_voicestudio_controls(
            inspect_runtime(self.voicestudio_runtime, probe_backend=False)
        )

    def _handle_voicestudio_event(self, event: str, payload: object) -> bool:
        if event == "voicestudio_status" and isinstance(payload, VoiceStudioRuntimeStatus):
            self._apply_voicestudio_status(payload)
            self._activate_voicestudio_tab(payload)
            return True
        if event == "voicestudio_launched":
            self._voicestudio_launching = False
            profile_lease = self._take_pending_voicestudio_profile()
            if self._voicestudio_launch_cancelled:
                self._voicestudio_launch_cancelled = False
                if profile_lease is not None:
                    profile_lease.release()
                return True
            try:
                self._mount_voicestudio_webview(profile_lease)
            except Exception as error:
                self._voicestudio_launch_failed = True
                self.voicestudio_status.set("Không thể nhúng giao diện VoiceStudio")
                self._append_log(f"VoiceStudio WebView error: {error}")
                self._show_voicestudio_bootstrap(
                    title="Không thể mở giao diện VoiceStudio",
                    detail=(
                        f"{error}\n\nBackend vẫn đang chạy. "
                        "Hãy thử lại hoặc mở trong trình duyệt."
                    ),
                    action="retry",
                )
                self._update_voicestudio_controls(
                    inspect_runtime(self.voicestudio_runtime, probe_backend=False),
                    running_override=True,
                )
                return True
            self.voicestudio_bootstrap_progress.stop()
            self._voicestudio_launch_failed = False
            self.voicestudio_status.set("VoiceStudio đang chạy trong Galaxy")
            self._update_voicestudio_controls(
                inspect_runtime(self.voicestudio_runtime, probe_backend=False),
                running_override=True,
            )
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
                self._voicestudio_auto_launch_attempted = False
                self._voicestudio_user_stopped = False
                self._voicestudio_launch_failed = False
                self.voicestudio_status.set("Cài runtime local hoàn tất")
                self._append_log("VoiceStudio local runtime installed.")
                self._refresh_voicestudio_status()
            else:
                self.voicestudio_status.set("Cài runtime local chưa hoàn tất")
                detail = self.voicestudio_controller.installer_log_tail(max_chars=1800)
                suffix = f"\n\nLog cuối:\n{detail}" if detail else ""
                self._append_log(
                    f"VoiceStudio installer failed with code {return_code}."
                    + (f"\n{detail}" if detail else "")
                )
                messagebox.showerror(
                    "Cài VoiceStudio thất bại",
                    f"Bộ cài đã dừng với mã {return_code}. "
                    "Bấm Cài runtime local để tiếp tục."
                    + suffix,
                )
                self._refresh_voicestudio_status()
            return True
        if event == "voicestudio_webview_failed":
            self._voicestudio_launch_failed = True
            self._destroy_voicestudio_webview()
            self.voicestudio_status.set("WebView2 không khởi tạo được")
            self._append_log(f"VoiceStudio WebView creation failed: {payload}")
            self._show_voicestudio_bootstrap(
                title="WebView2 không khởi tạo được",
                detail=(
                    f"Không thể nhúng giao diện: {payload}\n\n"
                    "Backend vẫn chạy; có thể mở trong trình duyệt từ menu Quản lý."
                ),
                action="retry",
            )
            self._update_voicestudio_controls(
                inspect_runtime(self.voicestudio_runtime, probe_backend=False),
                running_override=True,
            )
            return True
        if event == "voicestudio_error":
            self._voicestudio_launching = False
            if self._voicestudio_launch_cancelled:
                self._voicestudio_launch_cancelled = False
                return True
            self._voicestudio_launch_failed = True
            self.voicestudio_status.set("Không thể khởi động VoiceStudio")
            self._append_log(f"VoiceStudio error: {payload}")
            self._show_voicestudio_bootstrap(
                title="Không thể khởi động VoiceStudio",
                detail=f"{payload}\n\nKiểm tra log hoặc bấm Thử lại.",
                action="retry",
            )
            self._update_voicestudio_controls(
                inspect_runtime(self.voicestudio_runtime, probe_backend=False)
            )
            return True
        return False

    def _apply_voicestudio_status(self, status: VoiceStudioRuntimeStatus) -> None:
        if not self._voicestudio_launch_failed:
            self.voicestudio_status.set(status.message)
        self.voicestudio_version.set(f"VoiceStudio {status.version}")
        if (
            not self._voicestudio_launching
            and not self._voicestudio_installing
            and self.voicestudio_webview is None
            and not self._voicestudio_launch_failed
        ):
            if status.installed and self._voicestudio_user_stopped:
                self._show_voicestudio_bootstrap(
                    title="VoiceStudio đã dừng",
                    detail="Chọn Thử lại để khởi động VoiceStudio khi cần.",
                    action="retry",
                )
            elif status.installed:
                self._show_voicestudio_bootstrap(
                    title="VoiceStudio đã sẵn sàng",
                    detail=(
                        "Galaxy sẽ tự khởi động VoiceStudio khi tab này được mở.\n"
                        f"Runtime local: {status.python_path}"
                    ),
                )
            else:
                detail = ", ".join(status.missing_components) or "runtime cần cập nhật"
                self._show_voicestudio_bootstrap(
                    title="Cần cài runtime VoiceStudio",
                    detail=(
                        f"Snapshot đã đóng gói: {status.source_dir.name}\n"
                        f"Cần cài: {detail}"
                    ),
                    action="install" if status.snapshot_present else "none",
                )
        self._update_voicestudio_controls(status)

    def _update_voicestudio_controls(
        self,
        status: VoiceStudioRuntimeStatus,
        *,
        running_override: bool | None = None,
    ) -> None:
        installing = self._voicestudio_installing or self.voicestudio_controller.installer_running()
        running = (
            running_override
            if running_override is not None
            else status.backend_online or self.voicestudio_controller.is_running()
        )
        busy = installing or self._voicestudio_launching
        install_text = "Cập nhật runtime" if status.update_required else "Cài runtime local"
        needs_install = not status.installed

        self.voicestudio_install_button.configure(
            state="normal" if status.snapshot_present and not busy else "disabled",
            text=install_text,
        )
        self.voicestudio_bootstrap_install_button.configure(
            state="normal" if status.snapshot_present and not busy else "disabled",
            text=install_text,
        )
        if needs_install:
            self.voicestudio_install_button.grid()
        else:
            self.voicestudio_install_button.grid_remove()

        self.voicestudio_manage_menu.entryconfigure(
            0,
            state=(
                "normal"
                if status.installed and not busy and self.voicestudio_webview is None
                else "disabled"
            )
        )
        self.voicestudio_manage_menu.entryconfigure(
            1,
            state="normal" if self.voicestudio_webview is not None else "disabled",
        )
        self.voicestudio_manage_menu.entryconfigure(
            2,
            state="normal" if running else "disabled",
        )
        self.voicestudio_manage_menu.entryconfigure(
            4,
            state="normal" if status.snapshot_present and not busy else "disabled",
        )
        self.voicestudio_manage_menu.entryconfigure(
            5,
            state="normal" if running or busy else "disabled",
        )
