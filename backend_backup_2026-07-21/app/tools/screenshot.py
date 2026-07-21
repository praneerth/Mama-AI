import pyautogui
def handle_screenshot(command: str):
    if "screenshot" in command:
        pyautogui.screenshot("screenshot.png")
        return "Screenshot captured"
    return None