from app.llm.provider import llm_provider
class AIEngine:
    def __init__(self):
        self.provider = llm_provider
    def process(self, prompt: str) -> str:
        return self.provider.generate(prompt)
ai_engine = AIEngine()