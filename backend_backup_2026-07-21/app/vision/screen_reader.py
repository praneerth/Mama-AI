from app.cognition.observer import observe

def read_screen() -> str:
    """
    Observe the screen using OCR and return the parsed text.
    """
    obs = observe()
    return f"Read screen text:\n{obs.get('text', '')}"
