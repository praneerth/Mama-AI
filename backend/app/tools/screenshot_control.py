import pyautogui
import os

def take_screenshot() -> str:
    """
    Take a full desktop screenshot and save to screenshots/captured.png.
    """
    path = "screenshots/captured.png"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        pyautogui.screenshot(path)
        return f"Screenshot saved successfully to {path}"
    except Exception as e:
        return f"Failed to take screenshot: {e}"
