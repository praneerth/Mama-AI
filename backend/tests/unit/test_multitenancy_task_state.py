import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.api.auth import AuthenticatedPrincipal
from app.api.tasks import get_task, list_tasks, task_summary
from app.core.engine import engine
from app.core.principal_context import reset_current_principal, set_current_principal
from app.core.task import TaskRequest
from app.core.task_registry import TaskRegistry
from app.database.state_db import SQLiteStateStore


class TestMultiUserTaskState(unittest.TestCase):
    def setUp(self):
        engine.registry.clear()

    def tearDown(self):
        engine.registry.clear()

    def _principal(self, owner_id):
        return AuthenticatedPrincipal(
            owner_id=owner_id,
            authentication_method="test",
        )

    def _register(self, owner_id, command):
        request = TaskRequest(
            command=command,
            metadata={"owner_id": owner_id},
        )
        engine.registry.register(request)
        return request

    def test_registry_filters_by_owner(self):
        registry = TaskRegistry()
        first = TaskRequest(command="first", metadata={"owner_id": "user-1"})
        second = TaskRequest(command="second", metadata={"owner_id": "user-2"})
        registry.register(first)
        registry.register(second)

        visible = registry.list(owner_id="user-1")

        self.assertEqual([item.task_id for item in visible], [first.task_id])
        self.assertEqual(registry.count(owner_id="user-2"), 1)

    def test_task_api_hides_other_owner(self):
        own = self._register("user-1", "own task")
        other = self._register("user-2", "other task")
        token = set_current_principal(self._principal("user-1"))
        try:
            response = list_tasks(status=None, limit=20)
            summary = task_summary()

            self.assertEqual(response["count"], 1)
            self.assertEqual(response["tasks"][0]["task_id"], own.task_id)
            self.assertEqual(summary["total"], 1)

            with self.assertRaises(HTTPException) as context:
                get_task(other.task_id)
            self.assertEqual(context.exception.status_code, 404)
        finally:
            reset_current_principal(token)

    def test_state_store_round_trip_preserves_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStateStore(Path(directory) / "state.db")
            registry = TaskRegistry()
            record = registry.register(
                TaskRequest(
                    command="owned task",
                    metadata={"owner_id": "user-7"},
                )
            )
            store.save_task(record)

            self.assertIsNotNone(store.get_task(record.task_id, owner_id="user-7"))
            self.assertIsNone(store.get_task(record.task_id, owner_id="user-8"))
            self.assertEqual(len(store.list_tasks(owner_id="user-7")), 1)
            self.assertEqual(len(store.list_tasks(owner_id="user-8")), 0)

    def test_legacy_task_owner_migrates_from_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            with sqlite3.connect(path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE task_state (
                        task_id TEXT PRIMARY KEY,
                        command TEXT NOT NULL,
                        source TEXT NOT NULL,
                        autonomy_level INTEGER NOT NULL,
                        risk_level TEXT NOT NULL,
                        status TEXT NOT NULL,
                        message TEXT NOT NULL DEFAULT '',
                        output_json TEXT,
                        error TEXT,
                        evidence_json TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT
                    );
                    CREATE TABLE task_queue (
                        task_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL
                    );
                    INSERT INTO task_state (
                        task_id, command, source, autonomy_level,
                        risk_level, status, created_at, updated_at
                    ) VALUES (
                        'task-1', 'legacy', 'api', 1,
                        'low', 'pending', '2026-01-01', '2026-01-01'
                    );
                    INSERT INTO task_queue(task_id, owner_id)
                    VALUES ('task-1', 'account-user');
                    """
                )

            store = SQLiteStateStore(path)
            migrated = store.get_task("task-1")
            self.assertEqual(migrated["owner_id"], "account-user")


if __name__ == "__main__":
    unittest.main()
