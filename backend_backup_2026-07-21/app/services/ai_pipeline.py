from app.agent.intent_classifier import classify_intent
from app.services.ai_service import ask_ai

from app.database.memory_db import get_all_memory
from app.database.learning_db import get_all_learning


# =====================================================
# AI Pipeline
# =====================================================

def process_request(task: str):

    # -----------------------------
    # Intent
    # -----------------------------

    intent = classify_intent(task)

    # -----------------------------
    # Memory
    # -----------------------------

    memories = get_all_memory()

    memory_text = ""

    for m in memories[-5:]:

        try:
            memory_text += f"- {m.title}: {m.content}\n"
        except Exception:
            try:
                memory_text += f"- {m['title']}: {m['content']}\n"
            except Exception:
                pass

    # -----------------------------
    # Learning
    # -----------------------------

    learning = get_all_learning()

    learning_text = ""

    for item in learning[:5]:

        try:
            learning_text += f"- {item['task']} -> {item['solution']}\n"
        except Exception:
            pass

    # -----------------------------
    # Prompt
    # -----------------------------

    prompt = f"""
You are Mama AI.

User Task:
{task}

Intent:
{intent}

Previous Memory:
{memory_text}

Previous Learning:
{learning_text}

Return ONLY the action or response.
"""

    answer = ask_ai(prompt)

    return {
        "intent": intent,
        "thought": answer,
        "decision": answer,
        "plan": [answer] if answer else [],
    }