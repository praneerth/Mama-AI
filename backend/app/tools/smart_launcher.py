import subprocess

def launch_app(app_name: str) -> str:
    """
    Launch installed Windows applications using shell launcher.
    """
    app_name = app_name.lower().replace("open", "").replace("launch", "").strip()
    try:
        subprocess.Popen(f"start {app_name}", shell=True)
        return f"Launched {app_name}"
    except Exception as e:
        return f"Failed to launch {app_name}: {e}"
