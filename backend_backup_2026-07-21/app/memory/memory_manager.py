conversation_history = []

def add_message(role: str, text: str):
    conversation_history.append({
        "role": role,
        "text": text
    })

def get_history():
    return conversation_history

def clear_history():
    conversation_history.clear()