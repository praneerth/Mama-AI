from app.ai.providers.gemini import generate
from app.ai.prompts import SYSTEM_PROMPT

from app.memory.memory_manager import (
    add_message,
    get_history,
)

from app.tools.manager import execute_tool


def ask_ai(user_message: str, use_tools: bool = True):

    add_message("user", user_message)

    if use_tools:
        tool_result = execute_tool(user_message)

        if tool_result:
            add_message("assistant", tool_result)
            return tool_result

    history = ""

    for msg in get_history():
        history += f"{msg['role']}: {msg['text']}\n"

    prompt = f"""
{SYSTEM_PROMPT}

Conversation:

{history}

User:
{user_message}
"""

    answer = generate(prompt)

    if answer.startswith("ERROR"):
        return answer

    add_message("assistant", answer)

    return answer