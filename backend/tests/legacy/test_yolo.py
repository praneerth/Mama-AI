from app.vision.detector import analyze_objects

objects = analyze_objects()

print("\nDetected Objects:\n")

for obj in objects:
    print(obj)