class MessageBus:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, agent_name: str, callback):
        if agent_name not in self.subscribers:
            self.subscribers[agent_name] = []
        self.subscribers[agent_name].append(callback)

    def publish(self, sender: str, recipient: str, message: dict):
        if recipient in self.subscribers:
            for callback in self.subscribers[recipient]:
                try:
                    callback(sender, message)
                except Exception as e:
                    print(f"Error publishing to {recipient}: {e}")
message_bus = MessageBus()