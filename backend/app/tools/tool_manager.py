from app.tools.keyboard import handle_keyboard
from app.tools.browser import handle_browser
from app.tools.system import handle_system
from app.tools.files import handle_files
from app.tools.screenshot import handle_screenshot
from app.tools.automation import handle_automation
from app.tools.vision import handle_vision
from app.tools.window_control import handle_window
from app.tools.mouse import handle_mouse
from app.tools.cursor import handle_cursor
from app.tools.ui_elements import handle_ui
from app.tools.ui_click import handle_ui_click


TOOLS = [
    handle_keyboard,      # Keep this first
    handle_browser,
    handle_system,
    handle_files,
    handle_screenshot,
    handle_automation,
    handle_vision,
    handle_window,
    handle_mouse,
    handle_cursor,
    handle_ui,
    handle_ui_click,
]


def execute_tool(command: str):
    print(f"\nSearching tool for: {command}")

    for tool in TOOLS:
        print(f"Trying {tool.__name__}")

        try:
            result = tool(command)

            if result:
                print(f"✅ Matched {tool.__name__}")
                return result

        except Exception as e:
            print(f"❌ {tool.__name__} failed: {e}")

    print("❌ No tool matched.")
    return None