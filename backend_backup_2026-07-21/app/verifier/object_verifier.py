from app.tools.screenshot import take_screenshot
from app.vision.object_detector import detect_objects


def verify_objects(target_objects):

    screenshot = take_screenshot()

    print(f"Screenshot: {screenshot}")

    objects = detect_objects(screenshot)

    print("\n===== DETECTED OBJECTS =====")

    for obj in objects:
        print(obj)

    names = [obj["name"].lower() for obj in objects]

    for target in target_objects:

        if target.lower() in names:

            print(f"\nObject Verified: {target}")

            return True

    print("\nObject Verification Failed")

    return False