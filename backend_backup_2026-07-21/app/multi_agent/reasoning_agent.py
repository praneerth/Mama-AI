from app.ai.providers.gemini import generate
class ReasoningAgent:
    def __init__(self):
        self.role = "reasoner"

    def analyze(self, goal: str, context: str) -> str:
        prompt = f"Reasoning analysis for Goal: {goal}. Context: {context}. Is this action safe and how should we proceed?"
        print(f"[ReasoningAgent] Reasoning about: {goal}")
        return generate(prompt)