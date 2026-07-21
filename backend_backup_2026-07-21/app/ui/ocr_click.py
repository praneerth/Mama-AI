import re
import pyautogui

from app.vision.capture import capture_screen
from app.vision.ocr import detect_text


def normalize(text):
    """Remove spaces, punctuation and convert to lowercase."""
    return re.sub(r'[^a-z0-9]', '', text.lower())


def click_text(command):

    image_path = capture_screen()
    results = detect_text(image_path)

    # Remove action words
    target = command.lower().strip()

    for prefix in ["click ", "tap ", "press ", "select ", "open "]:
        if target.startswith(prefix):
            target = target[len(prefix):]

    target = normalize(target)

    print(f"\nSearching OCR for: {target}")

    for box, text, confidence in results:

        text_norm = normalize(text)

        print(f"OCR: '{text}' -> '{text_norm}'")

        if target in text_norm or text_norm in target:

            x = int((box[0][0] + box[2][0]) / 2)
            y = int((box[0][1] + box[2][1]) / 2)

            print(f"\nFound '{text}' ({confidence:.2f})")

            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click()

            return True

    print(f"\nText '{target}' not found.")

    return False