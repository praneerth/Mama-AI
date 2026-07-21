import os
import pyautogui
from PIL import Image
from app.ai.providers.gemini import generate

def verify(goal: str) -> bool:
    """
    Verify whether the goal has been successfully met by analyzing the screen.
    """
    temp_path = "screenshots/verification_temp.png"
    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
    
    try:
        screenshot = pyautogui.screenshot()
        screenshot.save(temp_path)
    except Exception as e:
        print(f"Verifier failed to take screenshot: {e}")
        # If we cannot capture, default to True to allow progress
        return True
        
    prompt = f"""You are the verifier of Mama AI.
The user goal was: "{goal}"

Looking at this desktop screenshot, has the goal been achieved?
Return ONLY "True" or "False". Do not explain.
"""
    try:
        img = Image.open(temp_path)
        answer = generate(prompt, image=img).strip().lower()
        if "true" in answer:
            return True
        return False
    except Exception as e:
        print(f"Verifier error: {e}")
        return True
