from app.ui.ui_detector import detect_ui


def verify_ui(ui_name):

    point = detect_ui(ui_name)

    if point is None:
        print(f"\nUI Verification Failed: {ui_name}")
        return False

    print(f"\nUI Verified: {ui_name}")
    print(f"Location: {point}")

    return True