import os
import time
import pyautogui
from PIL import Image

# Fallback path for screenshots
SCREENSHOT_DIR = "screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def observe() -> dict:
    """
    Observe the current screen state: take a screenshot, run OCR, and extract objects.
    """
    timestamp = int(time.time())
    screenshot_path = os.path.join(SCREENSHOT_DIR, f"screen_{timestamp}.png")
    
    try:
        screenshot = pyautogui.screenshot()
        screenshot.save(screenshot_path)
    except Exception as e:
        print(f"Error capturing screenshot: {e}")
        # Create a dummy image if screenshot fails
        screenshot = Image.new("RGB", (800, 600), color="black")
        screenshot.save(screenshot_path)
    
    ocr_text = ""
    # Try using pytesseract if available
    try:
        import pytesseract
        ocr_text = pytesseract.image_to_string(screenshot)
    except Exception as e_tess:
        print(f"Pytesseract not configured or failed: {e_tess}")
        # Try using easyocr if available
        try:
            import easyocr
            reader = easyocr.Reader(['en'])
            results = reader.readtext(screenshot_path)
            ocr_text = " ".join([r[1] for r in results])
        except Exception as e_easy:
            print(f"EasyOCR failed: {e_easy}")
            ocr_text = "Screen captured successfully. OCR unavailable."

    return {
        "text": ocr_text,
        "image_path": screenshot_path,
        "objects": [] # Custom objects detection can go here
    }
