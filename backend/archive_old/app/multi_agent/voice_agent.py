class VoiceAgent:
    def __init__(self):
        self.role = "voice"

    def speak(self, speech_text: str):
        print(f"[VoiceAgent] Speak output: {speech_text}")
        return speech_text