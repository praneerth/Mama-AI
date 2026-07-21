import pyautogui
import time

from app.tools.screenshot import take_screenshot
from app.vision.ui_locator import locate_object

print("Taking screenshot...")
image = take_screenshot()

point = locate_object(image, "laptop")

print("Found:", point)

if point:
    time.sleep(2)  # Gives you time to see the mouse move
    pyautogui.moveTo(point[0], point[1], duration=0.5)
    pyautogui.click()
    print("Clicked!")
else:
    print("Object not found.")