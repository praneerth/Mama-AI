class StateManager:

    def __init__(self):
        self.current_task = None
        self.status = "idle"

    def set_task(self, task):
        self.current_task = task
        self.status = "running"

    def get_task(self):
        return self.current_task

    def get_status(self):
        return self.status

    def complete(self):
        self.status = "completed"

    def failed(self):
        self.status = "failed"

    def reset(self):
        self.current_task = None
        self.status = "idle"

    def get_state(self):
        return {
            "task": self.current_task,
            "status": self.status,
        }


state_manager = StateManager()