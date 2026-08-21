from __future__ import annotations

import os
import re
import sys
from functools import lru_cache

_ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value

    for name in names:
        value = _read_windows_environment(name).strip()
        if value:
            return value

    return default


def set_user_environment(name: str, value: str) -> None:
    """Persist a value in the current Windows user's environment."""
    normalized_name = name.strip().upper()
    normalized_value = value.strip()
    if not _ENVIRONMENT_NAME_PATTERN.fullmatch(normalized_name):
        raise ValueError("Invalid environment variable name")
    if not normalized_value:
        raise ValueError("Environment variable value cannot be empty")
    if sys.platform != "win32":
        raise OSError("Saving user environment variables is only supported on Windows")

    try:
        import winreg
    except ImportError as error:  # pragma: no cover - Windows always provides winreg
        raise OSError("Windows Registry support is unavailable") from error

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
        winreg.SetValueEx(key, normalized_name, 0, winreg.REG_SZ, normalized_value)

    # Make the new key usable by this running app immediately. Registry remains
    # the source for future launches; no secret is written to app config.
    os.environ[normalized_name] = normalized_value
    _read_windows_environment.cache_clear()
    _broadcast_environment_change()


def _broadcast_environment_change() -> None:
    if sys.platform != "win32":  # pragma: no cover - Windows-only app
        return
    try:
        import ctypes

        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(  # type: ignore[attr-defined]
            0xFFFF,  # HWND_BROADCAST
            0x001A,  # WM_SETTINGCHANGE
            0,
            "Environment",
            0x0002,  # SMTO_ABORTIFHUNG
            5000,
            ctypes.byref(result),
        )
    except (AttributeError, OSError):
        # Registry persistence and the current process update already succeeded.
        pass


@lru_cache(maxsize=64)
def _read_windows_environment(name: str) -> str:
    if sys.platform != "win32":
        return ""

    try:
        import winreg
    except ImportError:
        return ""

    locations = [
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ]

    for hive, path in locations:
        try:
            with winreg.OpenKey(hive, path) as key:
                value, value_type = winreg.QueryValueEx(key, name)
        except OSError:
            continue

        if not isinstance(value, str) or not value.strip():
            continue
        if value_type == winreg.REG_EXPAND_SZ:
            value = os.path.expandvars(value)
        return value

    return ""
