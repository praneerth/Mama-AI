import time
import pyautogui

print("Switch to Chrome in 5 seconds...")
time.sleep(5)

# Move the mouse so you know the script is running
pyautogui.moveTo(500, 500, duration=1)

pyautogui.hotkey("ctrl", "l")
pyautogui.write("https://google.com", interval=0.03)
pyautogui.press("enter")

print("Done")