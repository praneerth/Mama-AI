from app.ai.providers.gemini import generate

def classify_intent(task: str) -> str:
    """
    Classify the user intent using keyword heuristics with LLM fallback.
    """
    task_lower = task.lower().strip()
    
    # 1. Keyword heuristics
    if any(kw in task_lower for kw in ["open", "launch", "run", "start"]):
        return "open_application"
    if any(kw in task_lower for kw in ["click", "press", "type", "keyboard", "mouse"]):
        return "desktop_automation"
    if any(kw in task_lower for kw in ["search", "google", "find"]):
        return "web_search"
    if any(kw in task_lower for kw in ["translate", "speak in", "how do you say"]):
        return "translation_or_language"
        
    # 2. LLM Fallback
    prompt = f"""Classify the intent of this user request:
"{task}"

Possible categories:
- open_application
- desktop_automation
- web_search
- translation_or_language
- general_chat

Return ONLY the category name. Do not explain.
"""
    intent = generate(prompt).strip().lower()
    for cat in ["open_application", "desktop_automation", "web_search", "translation_or_language", "general_chat"]:
        if cat in intent:
            return cat
            
    return "general_chat"
