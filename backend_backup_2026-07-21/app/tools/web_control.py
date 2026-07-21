import webbrowser
import urllib.parse

def open_website(text: str) -> str:
    """
    Detect web URLs and open them in the default browser.
    """
    words = text.split()
    for w in words:
        if "." in w and not w.endswith(".") and not w.startswith("app"):
            url = w
            if not url.startswith("http"):
                url = "https://" + url
            webbrowser.open(url)
            return f"Opened website: {url}"
    return ""

def search_web(query: str) -> str:
    """
    Perform a Google search for the specified query in browser.
    """
    query_str = query.lower().replace("search", "").strip()
    encoded = urllib.parse.quote(query_str)
    url = f"https://www.google.com/search?q={encoded}"
    webbrowser.open(url)
    return f"Searched Google for: {query_str}"
