"""Windows Win32 helpers for capture exclusion, click-through overlays, and DPI."""

from __future__ import annotations

import ctypes
import sys

IS_WINDOWS = sys.platform == "win32"

# Win32 constants
WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Windows 10 2004+ (build 19041)

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


def enable_per_monitor_dpi_awareness() -> bool:
    """Enable Per-Monitor V2 DPI awareness so capture and overlay coordinates align."""
    if not IS_WINDOWS:
        return False
    try:
        user32 = ctypes.windll.user32
        result = user32.SetProcessDpiAwarenessContext(
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        )
        return bool(result)
    except Exception:
        return False


def exclude_window_from_capture(hwnd: int) -> bool:
    """Hide a window from screen capture while keeping it visible on the monitor.

    Prevents live translation mode from re-capturing its own translated overlay.
    """
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        user32.SetWindowDisplayAffinity.restype = ctypes.c_bool
        return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


def set_window_click_through(hwnd: int, click_through: bool = True) -> bool:
    """Toggle WS_EX_TRANSPARENT + WS_EX_LAYERED so mouse events pass through."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        is_64bit = sys.maxsize > 2**32
        get_long = user32.GetWindowLongPtrW if is_64bit else user32.GetWindowLongW
        set_long = user32.SetWindowLongPtrW if is_64bit else user32.SetWindowLongW

        style = get_long(hwnd, GWL_EXSTYLE)
        if click_through:
            new_style = (
                style
                | WS_EX_LAYERED
                | WS_EX_TRANSPARENT
                | WS_EX_TOOLWINDOW
                | WS_EX_NOACTIVATE
            )
        else:
            new_style = style & ~WS_EX_TRANSPARENT
        set_long(hwnd, GWL_EXSTYLE, new_style)
        return True
    except Exception:
        return False


def set_auto_start_registry(enable: bool = True) -> bool:
    """Register or unregister WinScreenLens in Windows Run registry key for automatic startup."""
    if not IS_WINDOWS:
        return False
    try:
        import os
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "WinScreenLens"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                exe_path = sys.executable
                if getattr(sys, "frozen", False):
                    cmd = f'"{exe_path}"'
                else:
                    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    run_py = os.path.join(root, "run.py")
                    pythonw = os.path.join(os.path.dirname(exe_path), "pythonw.exe")
                    if os.path.isfile(pythonw):
                        cmd = f'"{pythonw}" "{run_py}"'
                    else:
                        cmd = f'"{exe_path}" "{run_py}"'
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def get_auto_start_registry() -> bool:
    """Return True if WinScreenLens is configured to auto-start with Windows."""
    if not IS_WINDOWS:
        return False
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "WinScreenLens"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, app_name)
            return True
    except Exception:
        return False


def get_window_rect_at_point(
    x: int, y: int, ignore_hwnds: set[int] | None = None
) -> tuple[int, int, int, int] | None:
    """Return (left, top, width, height) of the desktop window under mouse cursor for smart snapping."""
    if not IS_WINDOWS:
        return None
    try:
        import win32gui

        point = (int(x), int(y))
        hwnd = win32gui.WindowFromPoint(point)
        if not hwnd:
            return None

        # Find top-level ancestor if needed (GA_ROOT = 2)
        root_hwnd = win32gui.GetAncestor(hwnd, 2)
        target_hwnd = root_hwnd if root_hwnd else hwnd

        if ignore_hwnds and target_hwnd in ignore_hwnds:
            return None

        rect = win32gui.GetWindowRect(target_hwnd)
        left, top, right, bottom = rect
        w = max(1, right - left)
        h = max(1, bottom - top)
        if w > 40 and h > 40:
            return (left, top, w, h)
        return None
    except Exception:
        return None


def trim_process_memory() -> bool:
    """Hint Windows to trim idle working-set pages from RAM."""
    if not IS_WINDOWS:
        return False
    try:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.windll.psapi
        psapi.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
        return bool(psapi.EmptyWorkingSet(k32.GetCurrentProcess()))
    except Exception:
        return False
