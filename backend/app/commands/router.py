"""Command routing for native Mama AI desktop automation."""

from __future__ import annotations

from app.config import settings


def process_command(user_input):
    text = user_input.lower()

    if settings.CONTAINER_MODE:
        return (
            "ERROR: Desktop automation is unavailable in container mode. "
            "Run the native Mama AI desktop agent for host control."
        )

    if (
        "open camera" in text
        or "see camera" in text
        or "look around" in text
        or "what do you see" in text
    ):
        from app.vision.camera_vision import detect_objects

        return detect_objects()

    if (
        "read screen" in text
        or "what is on my screen" in text
        or "screen text" in text
    ):
        from app.vision.screen_reader import read_screen

        return read_screen()

    if (
        "screenshot" in text
        or "capture screen" in text
        or "take screenshot" in text
    ):
        from app.tools.screenshot_control import take_screenshot

        return take_screenshot()

    if text.startswith("close"):
        from app.tools.process_control import close_app

        result = close_app(text)
        if result:
            return result
        return "I could not find that running application."

    if text.startswith("open"):
        from app.tools.pc_control import open_app
        from app.tools.smart_launcher import launch_app
        from app.tools.web_control import open_website

        result = open_website(text)
        if result:
            return result
        result = open_app(text)
        if result:
            return result
        result = launch_app(text)
        if result:
            return result
        return "I could not find that application."

    if text.startswith("play"):
        from app.tools.youtube_control import play_youtube

        result = play_youtube(text)
        if result:
            return result

    if text.startswith("search"):
        from app.tools.web_control import search_web

        result = search_web(text)
        if result:
            return result

    from app.services.ai_service import ask_ai

    return ask_ai(user_input)
