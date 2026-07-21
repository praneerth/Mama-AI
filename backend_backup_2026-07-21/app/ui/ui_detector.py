from app.tools.screenshot import take_screenshot
from app.ui.template_matcher import find_template
from app.ui.ui_database import UI_TEMPLATES


def detect_ui(name):

    screenshot = take_screenshot()

    template = UI_TEMPLATES.get(name)

    if template is None:
        return None

    return find_template(screenshot, template)