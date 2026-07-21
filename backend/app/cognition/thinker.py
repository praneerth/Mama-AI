import os
from PIL import Image
from app.ai.providers.gemini import generate

def think(goal: str, observation: dict) -> str:
    """
    Think using Gemini to decide the next step based on the goal and screen state.
    """
    image_path = observation.get("image_path")
    ocr_text = observation.get("text", "")
    
    prompt = f"""You are the thinking brain of Mama AI.
The user's goal is: "{goal}"

Current Screen OCR Text:
{ocr_text}

Analyze the goal and the screen content.
Decide on the next logical action.
Possible options:
1. "Goal Achieved" - if the goal is fully accomplished.
2. "Ask User" - if you need human help, passwords, or clarification.
3. An action description (e.g. "Open Notepad", "Click on the Chrome icon", "Type hello", "Search for weather").

Return ONLY the decided option/action description. Do not explain.
"""
    try:
        if image_path and os.path.exists(image_path):
            img = Image.open(image_path)
            # Pass PIL Image and prompt to Gemini
            decision = generate(prompt, image=img)
        else:
            decision = generate(prompt)
        return decision.strip()
    except Exception as e:
        print(f"Thinker error: {e}")
        return "Ask User"
