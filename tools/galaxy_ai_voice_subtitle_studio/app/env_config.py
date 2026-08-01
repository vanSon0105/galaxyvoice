from __future__ import annotations

import os
import sys
from functools import lru_cache


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
