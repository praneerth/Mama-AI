import time

from app.tools.screenshot import take_screenshot
from app.vision.text_reader import extract_text

from app.database.analytics_db import add_analytics


def verify_task(task):

    start_time = time.time()

    image = take_screenshot()

    print(f"Screenshot captured: {image}")

    text = extract_text(image).lower()

    task_lower = task.lower()

    checks = {
        "chatgpt": "chatgpt",
        "youtube": "youtube",
        "google": "google",
        "gmail": "gmail",
        "calculator": "calculator",
        "notepad": "notepad",
        "paint": "paint",
        "settings": "settings",
        "chrome": "chrome",
    }

    success = True
    tool = "verification"

    for keyword, expected in checks.items():

        if keyword in task_lower:

            if expected in text:

                print(f"Verified: {expected} found.")

                success = True

            else:

                print(f"Verification failed: {expected} not found.")

                success = False

            break

    execution_time = round(time.time() - start_time, 2)

    try:

        add_analytics(
            task=task,
            tool=tool,
            success=success,
            execution_time=execution_time,
        )

    except Exception as e:

        print("Analytics Error:", e)

    return success