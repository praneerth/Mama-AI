from app.verifier.ocr_verifier import verify_ocr
from app.verifier.object_verifier import verify_objects
from app.verifier.ui_verifier import verify_ui
from app.verifier.vision_verifier import verify_vision


def verify(task):

    task = task.lower()

    print("\n========== HYBRID VERIFIER ==========")

    if "chatgpt" in task:

        if verify_ocr(["chatgpt"]):
            return True

        if verify_ui("chrome_addressbar"):
            return True

        if verify_vision(task):
            return True

        return False

    if "chrome" in task:

        if verify_ui("chrome_addressbar"):
            return True

        if verify_ocr(["chrome"]):
            return True

        if verify_vision(task):
            return True

        return False

    if "notepad" in task:

        if verify_ocr(["notepad"]):
            return True

        if verify_vision(task):
            return True

        return False

    return verify_vision(task)