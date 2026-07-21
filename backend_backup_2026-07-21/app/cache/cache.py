class InMemoryCache:
    def __init__(self):
        self._data = {}
    def get(self, key): return self._data.get(key)
    def set(self, key, value): self._data[key] = value