import os
import time
from google import genai
from app.config import settings

def generate(prompt: str, image=None) -> str:
    """
    Generate a response using Gemini 3.5 Flash via google-genai.
    Supports multimodal screen understanding when a screenshot image is passed.
    Includes robust retry logic for transient server errors (like 503).
    """
    retries = 3
    delay = 1
    
    for attempt in range(retries):
        try:
            api_key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
            client = genai.Client(api_key=api_key)
            
            contents = []
            if image is not None:
                contents.append(image)
            contents.append(prompt)
            
            response = client.models.generate_content(
                model=settings.AI_MODEL,
                contents=contents
            )
            return response.text if response.text else ""
        except Exception as e:
            if attempt == retries - 1:
                return f"ERROR: {str(e)}"
            print(f"Gemini API warning (attempt {attempt + 1}/{retries}): {e}. Retrying in {delay}s...")
            time.sleep(delay)
            delay *= 2

