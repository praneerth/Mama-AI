from app.ai.providers.gemini import generate
class AIBrain:
    def think(self, context: str) -> str:
        return generate(context)