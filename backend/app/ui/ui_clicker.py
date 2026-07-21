import pyautogui
from app.ui.ui_detector import detect_ui


def click_ui(name):

    point = detect_ui(name)

    if point is None:
        return False

    pyautogui.moveTo(point[0], point[1], duration=0.3)
    pyautogui.click()

    return True