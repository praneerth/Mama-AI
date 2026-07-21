import time
import pyautogui

print("Open Notepad or Chrome.")
print("Switch to it in 5 seconds...")

time.sleep(5)

print("Typing...")

pyautogui.write("Hello Mama AI", interval=0.1)

pyautogui.press("enter")

pyautogui.write("Keyboard works!")

print("Done")