from app.tools.screenshot import take_screenshot
from app.vision.text_reader import extract_text


def verify_ocr(keywords):

    screenshot = take_screenshot()

    print(f"Screenshot: {screenshot}")

    text = extract_text(screenshot)

    print("\n===== OCR TEXT =====")
    print(text)

    text = text.lower()

    for keyword in keywords:

        if keyword.lower() in text:

            print(f"\nOCR Verified: {keyword}")

            return True

    print("\nOCR Verification Failed")

    return False