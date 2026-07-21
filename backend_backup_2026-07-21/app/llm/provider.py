from app.ai.providers.gemini import generate
class LLMProvider:
    def generate(self, prompt: str) -> str:
        res = generate(prompt)
        if res.startswith("ERROR"):
            return f"Fallback message due to error: {res}"
        return res
llm_provider = LLMProvider()