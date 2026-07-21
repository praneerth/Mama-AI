class PromptManager:
    def format(self, template: str, vars: dict) -> str:
        return template.format(**vars)