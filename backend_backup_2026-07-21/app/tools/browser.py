import webbrowser
def handle_browser(command: str):
    if "open browser" in command or "search" in command:
        webbrowser.open("https://www.google.com")
        return "Opened default browser"
    return None