import unittest

from app.core.engine import MamaEngine
from app.core.event_bus import EventBus
from app.core.task import TaskRequest, TaskStatus
from app.core.task_registry import TaskRegistry


class TestMamaEngine(unittest.TestCase):

    def create_engine(self, executor):
        return MamaEngine(
            executor=executor,
            bus=EventBus(),
            registry=TaskRegistry(),
        )

    def test_successful_execution(self):
        engine = self.create_engine(
            lambda command: {
                "response": f"Executed: {command}"
            }
        )

        result = engine.execute("open chrome")
        record = engine.registry.get(result.task_id)

        self.assertTrue(result.success)
        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.message, "Executed: open chrome")
        self.assertIsNotNone(record)
        self.assertEqual(record.status, TaskStatus.SUCCEEDED)

    def test_task_request_is_supported(self):
        request = TaskRequest(
            command="open notepad",
            source="voice",
            autonomy_level=2,
        )

        engine = self.create_engine(lambda command: "Done")
        result = engine.execute(request)

        self.assertEqual(result.task_id, request.task_id)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Done")

    def test_empty_task_fails_safely(self):
        engine = self.create_engine(lambda command: "Done")

        result = engine.execute("   ")

        self.assertFalse(result.success)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("empty", result.error.lower())
        self.assertEqual(engine.registry.count(), 0)

    def test_executor_exception_is_captured(self):
        def failing_executor(command):
            raise RuntimeError("Executor unavailable")

        engine = self.create_engine(failing_executor)
        result = engine.execute("open chrome")
        record = engine.registry.get(result.task_id)

        self.assertFalse(result.success)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.error, "Executor unavailable")
        self.assertIsNotNone(record)
        self.assertEqual(record.status, TaskStatus.FAILED)

    def test_successful_task_publishes_events(self):
        bus = EventBus()
        registry = TaskRegistry()
        events = []

        bus.subscribe("*", lambda event: events.append(event))

        engine = MamaEngine(
            executor=lambda command: "Completed",
            bus=bus,
            registry=registry,
        )

        result = engine.execute("open calculator")

        self.assertTrue(result.success)
        self.assertEqual(
            [event.name for event in events],
            ["task.started", "task.succeeded"],
        )

    def test_failed_task_publishes_events(self):
        bus = EventBus()
        registry = TaskRegistry()
        events = []

        bus.subscribe("*", lambda event: events.append(event))

        def failing_executor(command):
            raise RuntimeError("Execution failed")

        engine = MamaEngine(
            executor=failing_executor,
            bus=bus,
            registry=registry,
        )

        result = engine.execute("perform failing task")

        self.assertFalse(result.success)
        self.assertEqual(
            [event.name for event in events],
            ["task.started", "task.failed"],
        )
        self.assertEqual(
            events[-1].payload["stage"],
            "execution",
        )

    def test_invalid_task_publishes_failure_event(self):
        bus = EventBus()
        events = []

        bus.subscribe("*", lambda event: events.append(event))

        engine = MamaEngine(
            executor=lambda command: "Completed",
            bus=bus,
            registry=TaskRegistry(),
        )

        result = engine.execute("   ")

        self.assertFalse(result.success)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "task.failed")
        self.assertEqual(
            events[0].payload["stage"],
            "validation",
        )

    def test_duplicate_task_is_rejected(self):
        request = TaskRequest(command="open chrome")
        engine = self.create_engine(lambda command: "Done")

        first_result = engine.execute(request)
        second_result = engine.execute(request)

        self.assertTrue(first_result.success)
        self.assertFalse(second_result.success)
        self.assertIn(
            "already registered",
            second_result.error.lower(),
        )
        self.assertEqual(engine.registry.count(), 1)

    def test_pre_registered_pending_task_can_execute(self):
        request = TaskRequest(command="open calculator")

        registry = TaskRegistry()
        registry.register(request)

        engine = MamaEngine(
            executor=lambda command: "Calculator opened.",
            bus=EventBus(),
            registry=registry,
        )

        result = engine.execute(request)
        record = registry.get(request.task_id)

        self.assertTrue(result.success)
        self.assertIsNotNone(record)
        self.assertEqual(
            record.status,
            TaskStatus.SUCCEEDED,
        )


if __name__ == "__main__":
    unittest.main()