from app.tools.manager import execute_tool
class ToolRouter:
    def route_and_execute(self, command): return execute_tool(command)