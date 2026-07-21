class PerceptionSystem:
    def parse_inputs(self, voice_data=None, screen_data=None):
        return {"voice": voice_data, "screen": screen_data}
perception = PerceptionSystem()