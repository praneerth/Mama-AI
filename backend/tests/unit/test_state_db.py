import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.approval_registry import (
    ApprovalRegistry,
    ApprovalStatus,
)
from app.core.task import (
    RiskLevel,
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from app.core.task_registry import TaskRegistry
from app.database.state_db import (
    APPROVAL_TABLE,
    TASK_TABLE,
    SQLiteStateStore,
)


class TestSQLiteStateStore(unittest.TestCase):

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()

        self.database_path = (
            Path(self.temp_directory.name)
            / "test_mama_ai.db"
        )

        self.store = SQLiteStateStore(
            self.database_path
        )

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_tables_are_created(self):
        with sqlite3.connect(
            self.database_path
        ) as connection:
            rows = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()

        table_names = {
            row[0]
            for row in rows
        }

        self.assertIn(TASK_TABLE, table_names)
        self.assertIn(APPROVAL_TABLE, table_names)

    def test_task_round_trip(self):
        request = TaskRequest(
            command="open notepad",
            source="api",
            autonomy_level=2,
        )

        registry = TaskRegistry()
        registry.register(request)
        registry.mark_running(request.task_id)

        result = TaskResult.succeeded(
            task_id=request.task_id,
            message="Notepad opened.",
            output={
                "application": "notepad",
            },
            evidence=[
                {
                    "type": "executor",
                    "name": "mock",
                }
            ],
        )

        record = registry.complete(result)

        self.store.save_task(record)

        loaded = self.store.get_task(
            request.task_id
        )

        self.assertIsNotNone(loaded)
        self.assertEqual(
            loaded["status"],
            TaskStatus.SUCCEEDED.value,
        )
        self.assertEqual(
            loaded["output"],
            {"application": "notepad"},
        )
        self.assertEqual(
            loaded["evidence"][0]["name"],
            "mock",
        )

    def test_task_upsert_updates_status(self):
        request = TaskRequest(
            command="open calculator"
        )

        registry = TaskRegistry()
        pending = registry.register(request)

        self.store.save_task(pending)

        running = registry.mark_running(
            request.task_id
        )

        self.store.save_task(running)

        loaded = self.store.get_task(
            request.task_id
        )

        self.assertEqual(
            loaded["status"],
            TaskStatus.RUNNING.value,
        )
        self.assertIsNotNone(
            loaded["started_at"]
        )

    def test_approval_round_trip_stores_only_hash(self):
        request = TaskRequest(
            command="delete the file report.pdf",
            risk_level=RiskLevel.HIGH,
        )

        task_registry = TaskRegistry()
        task_record = task_registry.register(request)

        self.store.save_task(task_record)

        approvals = ApprovalRegistry()

        approval = approvals.create(
            task_id=request.task_id,
            owner_id="user-1",
            command=request.command,
            risk_level=RiskLevel.HIGH,
            reasons=[
                "File deletion requires approval."
            ],
        )

        grant = approvals.approve(
            approval.approval_id,
            owner_id="user-1",
        )

        approved_record = approvals.get(
            approval.approval_id
        )

        self.store.save_approval(
            approved_record
        )

        loaded = self.store.get_approval(
            approval.approval_id
        )

        self.assertIsNotNone(loaded)
        self.assertEqual(
            loaded["status"],
            ApprovalStatus.APPROVED.value,
        )
        self.assertNotEqual(
            loaded["token_hash"],
            grant.token,
        )
        self.assertEqual(
            len(loaded["token_hash"]),
            64,
        )

    def test_status_filters(self):
        first = TaskRequest(
            command="open notepad"
        )
        second = TaskRequest(
            command="open calculator"
        )

        registry = TaskRegistry()

        first_record = registry.register(first)
        second_record = registry.register(second)

        registry.mark_running(first.task_id)

        first_result = TaskResult.succeeded(
            task_id=first.task_id,
            message="Done",
        )

        first_record = registry.complete(
            first_result
        )
        second_record = registry.get(
            second.task_id
        )

        self.store.save_task(first_record)
        self.store.save_task(second_record)

        succeeded = self.store.list_tasks(
            status="succeeded"
        )
        pending = self.store.list_tasks(
            status="pending"
        )

        self.assertEqual(len(succeeded), 1)
        self.assertEqual(
            succeeded[0]["task_id"],
            first.task_id,
        )

        self.assertEqual(len(pending), 1)
        self.assertEqual(
            pending[0]["task_id"],
            second.task_id,
        )


if __name__ == "__main__":
    unittest.main()