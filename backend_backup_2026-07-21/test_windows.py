from pywinauto import Desktop

windows = Desktop(backend="uia").windows()

for window in windows:
    print(window.window_text())