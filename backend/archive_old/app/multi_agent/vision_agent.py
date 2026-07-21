import os
import pyautogui
from PIL import Image
class VisionAgent:
    def __init__(self):
        self.role = "vision"

    def capture_and_analyze(self) -> dict:
        print("[VisionAgent] Capturing screen state...")
        screenshot_path = "screenshot.png"
        try:
            pyautogui.screenshot(screenshot_path)
            # Verify file exists
            if os.path.exists(screenshot_path):
                img = Image.open(screenshot_path)
                return {"success": True, "path": screenshot_path, "size": img.size}
        except Exception as e:
            return {"success": False, "error": str(e)}
        return {"success": False, "error": "Unknown error"}