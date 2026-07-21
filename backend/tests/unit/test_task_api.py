import unittest

from fastapi import HTTPException

from app.api.tasks import get_task, list_tasks, task_summary
from app.core.engine import engine
from app.core.task import TaskRequest, TaskResult


class TestTaskAPI(unittest.TestCase):

    def setUp(self):
        engine.registry.clear()

    def tearDown(self):
        engine.registry.clear()

    def create_successful_task(self):
        request = TaskRequest(command="open chrome")

        engine.registry.register(request)
        engine.registry.mark_running(request.task_id)

        result = TaskResult.succeeded(
            task_id=request.task_id,
            message="Chrome opened.",
            output={"application": "chrome"},
        )

        engine.registry.complete(result)

        return request

    def test_list_tasks(self):
        request = self.create_successful_task()

        response = list_tasks(
            status=None,
            limit=20,
        )

        self.assertTrue(response["success"])
        self.assertEqual(response["count"], 1)
        self.assertEqual(
            response["tasks"][0]["task_id"],
            request.task_id,
        )

    def test_filter_tasks_by_status(self):
        self.create_successful_task()

        response = list_tasks(
            status="succeeded",
            limit=20,
        )

        self.assertEqual(response["count"], 1)
        self.assertEqual(
            response["tasks"][0]["status"],
            "succeeded",
        )

    def test_get_task(self):
        request = self.create_successful_task()

        response = get_task(request.task_id)

        self.assertTrue(response["success"])
        self.assertEqual(
            response["task"]["task_id"],
            request.task_id,
        )
        self.assertEqual(
            response["task"]["status"],
            "succeeded",
        )

    def test_missing_task_returns_404(self):
        with self.assertRaises(HTTPException) as context:
            get_task("missing-task")

        self.assertEqual(
            context.exception.status_code,
            404,
        )

    def test_task_summary(self):
        self.create_successful_task()

        response = task_summary()

        self.assertTrue(response["success"])
        self.assertEqual(response["total"], 1)
        self.assertEqual(
            response["counts"]["succeeded"],
            1,
        )
        self.assertEqual(
            response["counts"]["running"],
            0,
        )


if __name__ == "__main__":
    unittest.main()