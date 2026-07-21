from app.tools.manager import execute_tool

def act(step: str) -> str:
    """
    Execute a plan step using system tools.
    """
    return execute_tool(step)
