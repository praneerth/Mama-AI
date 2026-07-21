import webbrowser
class BrowserAgent:
    def __init__(self):
        self.role = "browser"

    def open_url(self, url: str) -> str:
        print(f"[BrowserAgent] Opening browser URL: {url}")
        webbrowser.open(url)
        return f"Opened browser link {url}" 