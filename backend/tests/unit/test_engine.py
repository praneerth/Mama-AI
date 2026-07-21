import unittest

from app.core.engine import MamaEngine
from app.core.event_bus import EventBus
from app.core.task import TaskRequest, TaskStatus


class TestMamaEngine(unittest.TestCase):

    def test_successful_execution(self):
        engine = MamaEngine(
            executor=lambda command: {
                "response": f"Executed: {command}"
            },
            bus=EventBus(),
        )

        result = engine.execute("open chrome")

        self.assertTrue(result.success)
        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.message, "Executed: open chrome")
        self.assertEqual(
            result.output,
            {"response": "Executed: open chrome"},
        )

    def test_task_request_is_supported(self):
        request = TaskRequest(
            command="open notepad",
            source="voice",
            autonomy_level=2,
        )

        engine = MamaEngine(
            executor=lambda command: "Done",
            bus=EventBus(),
        )

        result = engine.execute(request)

        self.assertEqual(result.task_id, request.task_id)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Done")

    def test_empty_task_fails_safely(self):
        engine = MamaEngine(
            executor=lambda command: "Done",
            bus=EventBus(),
        )

        result = engine.execute("   ")

        self.assertFalse(result.success)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("empty", result.error.lower())

    def test_executor_exception_is_captured(self):
        def failing_executor(command):
            raise RuntimeError("Executor unavailable")

        engine = MamaEngine(
            executor=failing_executor,
            bus=EventBus(),
        )

        result = engine.execute("open chrome")

        self.assertFalse(result.success)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.error, "Executor unavailable")

    def test_successful_task_publishes_events(self):
        bus = EventBus()
        events = []

        bus.subscribe("*", lambda event: events.append(event))

        engine = MamaEngine(
            executor=lambda command: "Completed",
            bus=bus,
        )

        result = engine.execute("open calculator")

        self.assertTrue(result.success)
        self.assertEqual(
            [event.name for event in events],
            ["task.started", "task.succeeded"],
        )
        self.assertEqual(
            events[0].payload["task_id"],
            result.task_id,
        )
        self.assertEqual(
            events[1].payload["task_id"],
            result.task_id,
        )

    def test_failed_task_publishes_events(self):
        bus = EventBus()
        events = []

        bus.subscribe("*", lambda event: events.append(event))

        def failing_executor(command):
            raise RuntimeError("Execution failed")

        engine = MamaEngine(
            executor=failing_executor,
            bus=bus,
        )

        result = engine.execute("perform failing task")

        self.assertFalse(result.success)
        self.assertEqual(
            [event.name for event in events],
            ["task.started", "task.failed"],
        )
        self.assertEqual(
            events[1].payload["stage"],
            "execution",
        )
        self.assertEqual(
            events[1].payload["error"],
            "Execution failed",
        )

    def test_invalid_task_publishes_failure_event(self):
        bus = EventBus()
        events = []

        bus.subscribe("*", lambda event: events.append(event))

        engine = MamaEngine(
            executor=lambda command: "Completed",
            bus=bus,
        )

        result = engine.execute("   ")

        self.assertFalse(result.success)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "task.failed")
        self.assertEqual(
            events[0].payload["stage"],
            "validation",
        )


if __name__ == "__main__":
    unittest.main()