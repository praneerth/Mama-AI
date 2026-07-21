import webbrowser
import urllib.parse

def play_youtube(video_name: str) -> str:
    """
    Search and play YouTube video in the default browser.
    """
    video_query = video_name.lower().replace("play", "").replace("youtube", "").strip()
    encoded = urllib.parse.quote(video_query)
    url = f"https://www.youtube.com/results?search_query={encoded}"
    webbrowser.open(url)
    return f"Opened YouTube search for: {video_query}"
