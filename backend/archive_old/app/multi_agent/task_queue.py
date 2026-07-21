import queue
class AgentTaskQueue:
    def __init__(self):
        self._queue = queue.Queue()

    def add_task(self, task: dict):
        self._queue.put(task)

    def get_task(self):
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def is_empty(self):
        return self._queue.empty()
task_queue = AgentTaskQueue()