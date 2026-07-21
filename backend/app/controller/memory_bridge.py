memory = []


def remember(item):
    memory.append(item)


def recall():
    return memory


def clear():
    memory.clear()