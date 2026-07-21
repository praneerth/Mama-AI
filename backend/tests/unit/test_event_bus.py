import unittest

from app.core.event_bus import Event, EventBus


class TestEventBus(unittest.TestCase):

    def setUp(self):
        self.bus = EventBus()

    def test_event_creation(self):
        event = Event(
            name="task.started",
            payload={"task_id": "123"},
            source="engine",
        )

        self.assertEqual(event.name, "task.started")
        self.assertEqual(event.payload["task_id"], "123")
        self.assertEqual(event.source, "engine")
        self.assertTrue(event.event_id)

    def test_subscriber_receives_event(self):
        received = []

        self.bus.subscribe(
            "task.succeeded",
            lambda event: received.append(event),
        )

        published = self.bus.publish(
            "task.succeeded",
            {"task_id": "123"},
            source="engine",
        )

        self.assertEqual(len(received), 1)
        self.assertIs(received[0], published)

    def test_duplicate_subscription_is_prevented(self):
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe("task.started", handler)
        self.bus.subscribe("task.started", handler)

        self.bus.publish("task.started")

        self.assertEqual(len(received), 1)
        self.assertEqual(
            self.bus.subscriber_count("task.started"),
            1,
        )

    def test_unsubscribe(self):
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe("task.failed", handler)

        removed = self.bus.unsubscribe(
            "task.failed",
            handler,
        )

        self.bus.publish("task.failed")

        self.assertTrue(removed)
        self.assertEqual(received, [])

    def test_failing_handler_does_not_block_others(self):
        received = []

        def failing_handler(event):
            raise RuntimeError("Handler failure")

        def working_handler(event):
            received.append(event.name)

        self.bus.subscribe("task.started", failing_handler)
        self.bus.subscribe("task.started", working_handler)

        self.bus.publish("task.started")

        self.assertEqual(received, ["task.started"])

    def test_wildcard_subscriber_receives_all_events(self):
        received = []

        self.bus.subscribe(
            "*",
            lambda event: received.append(event.name),
        )

        self.bus.publish("task.started")
        self.bus.publish("task.succeeded")

        self.assertEqual(
            received,
            ["task.started", "task.succeeded"],
        )


if __name__ == "__main__":
    unittest.main()