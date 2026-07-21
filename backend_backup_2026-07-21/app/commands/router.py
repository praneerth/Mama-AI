from app.services.ai_service import ask_ai

from app.tools.pc_control import open_app
from app.tools.smart_launcher import launch_app
from app.tools.process_control import close_app
from app.tools.web_control import open_website, search_web
from app.tools.youtube_control import play_youtube
from app.tools.screenshot_control import take_screenshot

from app.vision.screen_reader import read_screen
from app.vision.camera_vision import detect_objects


def process_command(user_input):

    text = user_input.lower()


    # Camera vision command
    if (
        "open camera" in text
        or "see camera" in text
        or "look around" in text
        or "what do you see" in text
    ):
        return detect_objects()


    # Read screen command
    if (
        "read screen" in text
        or "what is on my screen" in text
        or "screen text" in text
    ):
        return read_screen()


    # Screenshot command
    if (
        "screenshot" in text
        or "capture screen" in text
        or "take screenshot" in text
    ):
        return take_screenshot()


    # Close applications
    if text.startswith("close"):

        result = close_app(text)

        if result:
            return result

        return "I could not find that running application."


    # Open applications and websites
    if text.startswith("open"):

        # Website
        result = open_website(text)

        if result:
            return result


        # Known applications
        result = open_app(text)

        if result:
            return result


        # Installed applications
        result = launch_app(text)

        if result:
            return result


        return "I could not find that application."


    # YouTube
    if text.startswith("play"):

        result = play_youtube(text)

        if result:
            return result


    # Search
    if text.startswith("search"):

        result = search_web(text)

        if result:
            return result


    # Gemini AI
    return ask_ai(user_input)