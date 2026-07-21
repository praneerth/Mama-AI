from app.vision.vision_ai import analyze_image

answer = analyze_image(
    "test.png",
    "Describe everything you see on this screen."
)

print(answer)