from app.vision.screen_analyzer import analyze_screen

result = analyze_screen()

print("\n===== GEMINI =====\n")
print(result["vision"])

print("\n===== OCR =====\n")
print(result["text"])

print("\n===== OBJECTS =====\n")
print(result["objects"])