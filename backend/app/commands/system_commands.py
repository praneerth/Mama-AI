import os

def execute(command: str):
    command = command.lower()

    if "chrome" in command:
        os.system("start chrome")
        return "Opening Chrome."

    elif "notepad" in command:
        os.system("start notepad")
        return "Opening Notepad."

    elif "calculator" in command:
        os.system("start calc")
        return "Opening Calculator."

    elif "paint" in command:
        os.system("start mspaint")
        return "Opening Paint."

    elif "command prompt" in command or "cmd" in command:
        os.system("start cmd")
        return "Opening Command Prompt."

    return None