class ExecutionSandbox:
    def run_safe(self, code: str):
        return exec(code)