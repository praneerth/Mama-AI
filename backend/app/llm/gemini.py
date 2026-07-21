from app.ai.providers.gemini import generate
class GeminiModel:
    def generate(self, prompt: str) -> str:
        return generate(prompt)