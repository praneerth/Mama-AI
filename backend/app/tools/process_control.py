import subprocess

def close_app(app_name: str) -> str:
    """
    Close running Windows application processes using taskkill.
    """
    app_name = app_name.lower().replace("close", "").replace("kill", "").strip()
    try:
        if "chrome" in app_name:
            subprocess.run("taskkill /f /im chrome.exe", shell=True, capture_output=True)
            return "Closed Chrome"
        elif "calculator" in app_name or "calc" in app_name:
            subprocess.run("taskkill /f /im CalculatorApp.exe", shell=True, capture_output=True)
            return "Closed Calculator"
        elif "notepad" in app_name:
            subprocess.run("taskkill /f /im notepad.exe", shell=True, capture_output=True)
            return "Closed Notepad"
        
        subprocess.run(f"taskkill /f /im {app_name}.exe", shell=True, capture_output=True)
        return f"Closed process: {app_name}"
    except Exception as e:
        return f"Error closing process: {e}"
