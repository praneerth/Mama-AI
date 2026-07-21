from app.tools.screenshot import take_screenshot
from app.vision.vision_ai import analyze_image


def verify_vision(task):

    screenshot = take_screenshot()

    prompt = f"""
You are verifying whether a desktop task succeeded.

Task:
{task}

Look carefully at the screenshot.

Reply with only one word:

YES
NO
"""

    answer = analyze_image(
        screenshot,
        prompt,
    )

    print("\n===== GEMINI VISION =====")
    print(answer)

    return "YES" in answer.upper()