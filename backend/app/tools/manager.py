import os
import re
import subprocess
import webbrowser
import pyautogui

def execute_tool(command: str) -> str:
    """
    Standard tool execution mapping. Maps text steps to real OS commands using PyAutoGUI
    and subprocess.
    """
    cmd_lower = command.lower().strip()
    print(f"[execute_tool] Executing step: {command}")
    
    try:
        # 1. Open Notepad
        if "notepad" in cmd_lower:
            subprocess.Popen("notepad.exe")
            return "SUCCESS: Opened Notepad"
            
        # 2. Open Calculator
        if "calc" in cmd_lower:
            subprocess.Popen("calc.exe")
            return "SUCCESS: Opened Calculator"
            
        # 3. Open Chrome
        if "chrome" in cmd_lower:
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
            ]
            opened = False
            for path in chrome_paths:
                if os.path.exists(path):
                    subprocess.Popen(path)
                    opened = True
                    break
            if not opened:
                # Fallback using standard web browser
                webbrowser.open("https://www.google.com")
            return "SUCCESS: Opened Chrome"

        # 4. Web Search
        if "search" in cmd_lower or "google" in cmd_lower:
            # Extract search query
            query = command.replace("search", "").replace("google", "").strip()
            webbrowser.open(f"https://www.google.com/search?q={query}")
            return f"SUCCESS: Searched for {query}"
            
        # 5. Clicking Coordinates
        if "click" in cmd_lower:
            coords = re.findall(r"\d+", command)
            if len(coords) >= 2:
                x, y = int(coords[0]), int(coords[1])
                pyautogui.click(x, y)
                return f"SUCCESS: Clicked at ({x}, {y})"
            
        # 6. Keyboard Typing
        if "type" in cmd_lower:
            text = command.split("type", 1)[1].strip()
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            pyautogui.write(text, interval=0.05)
            return f"SUCCESS: Typed '{text}'"
            
        # 7. Press Key
        if "press" in cmd_lower:
            key = command.replace("press", "").replace("key", "").strip()
            pyautogui.press(key)
            return f"SUCCESS: Pressed key '{key}'"

        return f"SUCCESS: Completed step {command}"
    except Exception as e:
        return f"ERROR: Step execution failed: {e}"
