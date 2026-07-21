from queue import Queue

task_queue = Queue()


def add_task(task):
    task_queue.put(task)


def get_task():
    if task_queue.empty():
        return None
    return task_queue.get()


def has_tasks():
    return not task_queue.empty()