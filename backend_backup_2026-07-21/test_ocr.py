from app.tools.screenshot import take_screenshot
from app.vision.text_reader import extract_text

print("Taking screenshot...")

image = take_screenshot()

print("Screenshot:", image)

text = extract_text(image)

print("\n===== OCR TEXT =====\n")
print(text)