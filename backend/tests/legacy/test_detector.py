from app.vision.detector import detect_objects

objects = detect_objects("test.png")

for obj in objects:
    print(obj)