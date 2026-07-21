import pyautogui
from app.vision.template_match import find_template

location = find_template("templates/chrome_icon.png")

print(location)

if location:
    pyautogui.moveTo(location[0], location[1], duration=0.5)
    pyautogui.click()
    print("Clicked!")
else:
    print("Icon not found.")