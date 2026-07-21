from app.tools.manager import execute_tool
class DesktopAgent:
    def __init__(self):
        self.role = "desktop"

    def execute_action(self, action: str) -> str:
        print(f"[DesktopAgent] Executing system tool action: {action}")
        return execute_tool(action)