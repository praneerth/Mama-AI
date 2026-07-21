import time

from app.tools.system import handle_system
from app.tools.keyboard import handle_keyboard

print("Opening Chrome...")

handle_system("open chrome")

time.sleep(1)

handle_keyboard("press ctrl l")

time.sleep(0.5)

handle_keyboard('type "THIS IS A TEST"')

time.sleep(0.5)

handle_keyboard("press enter")