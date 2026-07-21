import subprocess
import time

from app.tools.keyboard import handle_keyboard

# Open Chrome
subprocess.Popen("start chrome", shell=True)

# Wait for Chrome to open
time.sleep(3)

# Focus address bar
handle_keyboard("press ctrl l")

time.sleep(0.5)

# Type search
handle_keyboard('type "ChatGPT"')

time.sleep(0.5)

# Search
handle_keyboard("press enter")