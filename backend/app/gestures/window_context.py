"""Best-effort foreground-window context for Windows profile selection."""

from __future__ import annotations

import os


def foreground_window_title() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        handle = user32.GetForegroundWindow()
        if not handle:
            return ""
        length = user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        return buffer.value.strip()
    except Exception:
        return ""


class WindowsEmergencyHotkey:
    """Edge-triggered Ctrl+Alt+G detector using the Windows API."""

    VK_CONTROL = 0x11
    VK_MENU = 0x12
    VK_G = 0x47

    def __init__(self) -> None:
        self._pressed = False

    def poll(self) -> bool:
        if os.name != "nt":
            return False
        try:
            import ctypes

            state = ctypes.windll.user32.GetAsyncKeyState
            active = all(
                state(key) & 0x8000
                for key in (self.VK_CONTROL, self.VK_MENU, self.VK_G)
            )
        except Exception:
            return False
        triggered = active and not self._pressed
        self._pressed = active
        return triggered
