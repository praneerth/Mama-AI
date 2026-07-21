class TaskDispatcher:
    def dispatch(self, task):
        print(f"Dispatching: {task}")
        return True
dispatcher = TaskDispatcher()