import pyautogui
def handle_mouse(command: str):
    if "click" in command:
        pyautogui.click()
        return "Clicked mouse"
    return None