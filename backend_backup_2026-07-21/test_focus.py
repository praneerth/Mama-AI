import time
import pygetwindow as gw

print("Open Chrome manually first...")
time.sleep(5)

active = gw.getActiveWindow()

if active:
    print("Active Window:", active.title)
else:
    print("No active window")