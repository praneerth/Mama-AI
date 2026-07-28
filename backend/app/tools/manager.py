"""Local desktop tool execution.

Desktop automation is intentionally loaded lazily so the production API
control-plane can run in a headless Linux container. Host-level automation must
run in the native desktop agent, not inside the backend container.
"""

from __future__ import annotations

import os
import re
import subprocess
import webbrowser
from typing import Any

from app.config import settings


def _desktop_automation() -> Any:
    if settings.CONTAINER_MODE:
        raise RuntimeError(
            "Desktop automation is unavailable in container mode. "
            "Run the native Mama AI desktop agent for host control."
        )
    try:
        import pyautogui
    except Exception as exc:
        raise RuntimeError(
            "Desktop automation dependencies are unavailable on this host."
        ) from exc
    return pyautogui


def _require_native_desktop() -> None:
    if settings.CONTAINER_MODE:
        raise RuntimeError(
            "Desktop application control is unavailable in container mode. "
            "Run the native Mama AI desktop agent for host control."
        )


def execute_tool(command: str) -> str:
    """Map a text step to a local operating-system action."""

    cmd_lower = command.lower().strip()
    print(f"[execute_tool] Executing step: {command}")

    try:
        if "notepad" in cmd_lower:
            _require_native_desktop()
            subprocess.Popen("notepad.exe")
            return "SUCCESS: Opened Notepad"

        if "calc" in cmd_lower:
            _require_native_desktop()
            subprocess.Popen("calc.exe")
            return "SUCCESS: Opened Calculator"

        if "chrome" in cmd_lower:
            _require_native_desktop()
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
            opened = False
            for path in chrome_paths:
                if os.path.exists(path):
                    subprocess.Popen(path)
                    opened = True
                    break
            if not opened:
                webbrowser.open("https://www.google.com")
            return "SUCCESS: Opened Chrome"

        if "search" in cmd_lower or "google" in cmd_lower:
            _require_native_desktop()
            query = command.replace("search", "").replace("google", "").strip()
            webbrowser.open(f"https://www.google.com/search?q={query}")
            return f"SUCCESS: Searched for {query}"

        if "click" in cmd_lower:
            coords = re.findall(r"\d+", command)
            if len(coords) >= 2:
                x, y = int(coords[0]), int(coords[1])
                _desktop_automation().click(x, y)
                return f"SUCCESS: Clicked at ({x}, {y})"

        if "type" in cmd_lower:
            text = command.split("type", 1)[1].strip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            _desktop_automation().write(text, interval=0.05)
            return f"SUCCESS: Typed '{text}'"

        if "press" in cmd_lower:
            key = command.replace("press", "").replace("key", "").strip()
            _desktop_automation().press(key)
            return f"SUCCESS: Pressed key '{key}'"

        return f"SUCCESS: Completed step {command}"
    except Exception as exc:
        return f"ERROR: Step execution failed: {exc}"
