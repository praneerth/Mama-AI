import pyautogui
def handle_keyboard(command: str):
    if "type" in command:
        pyautogui.write(command.replace("type", "").strip())
        return "Typed keyboard text"
    return None