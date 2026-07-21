import subprocess
import os

def open_app(app_name: str) -> str:
    """
    Open common Windows applications.
    """
    app_name = app_name.lower().replace("open", "").strip()
    if "calculator" in app_name or "calc" in app_name:
        subprocess.Popen("calc.exe")
        return "Opened Calculator"
    elif "notepad" in app_name:
        subprocess.Popen("notepad.exe")
        return "Opened Notepad"
    elif "chrome" in app_name:
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for p in paths:
            if os.path.exists(p):
                subprocess.Popen(p)
                return "Opened Chrome"
        try:
            subprocess.Popen("start chrome", shell=True)
            return "Opened Chrome"
        except Exception:
            return "Chrome not found"
    elif "paint" in app_name or "mspaint" in app_name:
        subprocess.Popen("mspaint.exe")
        return "Opened Paint"
    return ""
