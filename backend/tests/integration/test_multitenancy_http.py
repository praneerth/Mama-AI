import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api import history as history_api
from app.api.auth import AuthenticatedPrincipal, require_principal
from app.api.history import router as history_router
from app.api.memory import router as memory_router
from app.api.tasks import router as tasks_router
from app.core.engine import engine
from app.core.principal_context import reset_current_principal, set_current_principal
from app.core.task import TaskRequest
from app.database import database, memory_db
from app.database.attempt_audit_db import SQLiteAttemptAuditStore


app = FastAPI()
app.include_router(tasks_router)
app.include_router(memory_router)
app.include_router(history_router)


async def test_principal(request: Request):
    owner_id = request.headers.get("x-test-owner", "").strip()
    principal = AuthenticatedPrincipal(
        owner_id=owner_id or "local-user",
        authentication_method="integration_test",
    )
    token = set_current_principal(principal)
    try:
        yield principal
    finally:
        reset_current_principal(token)


app.dependency_overrides[require_principal] = test_principal


class TestMultiUserDataIsolationHTTP(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = str(
            Path(self.temp_directory.name) / "multitenancy-http.db"
        )
        self.database_patcher = patch.object(
            database,
            "DATABASE_PATH",
            self.database_path,
        )
        self.database_patcher.start()
        database.initialize_database()

        self.audit_store = SQLiteAttemptAuditStore(self.database_path)
        self.audit_patcher = patch.object(
            history_api,
            "attempt_audit_store",
            self.audit_store,
        )
        self.audit_patcher.start()

        engine.registry.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        engine.registry.clear()
        self.audit_patcher.stop()
        self.database_patcher.stop()
        self.temp_directory.cleanup()

    @staticmethod
    def headers(owner_id: str) -> dict[str, str]:
        return {"X-Test-Owner": owner_id}

    @staticmethod
    def register_task(owner_id: str, command: str) -> TaskRequest:
        request = TaskRequest(
            command=command,
            metadata={"owner_id": owner_id},
        )
        engine.registry.register(request)
        return request

    def test_task_list_and_detail_hide_other_owner(self) -> None:
        first = self.register_task("user-1", "first")
        second = self.register_task("user-2", "second")

        listed = self.client.get("/tasks", headers=self.headers("user-1"))
        own = self.client.get(
            f"/tasks/{first.task_id}",
            headers=self.headers("user-1"),
        )
        hidden = self.client.get(
            f"/tasks/{second.task_id}",
            headers=self.headers("user-1"),
        )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["count"], 1)
        self.assertEqual(listed.json()["tasks"][0]["task_id"], first.task_id)
        self.assertEqual(own.status_code, 200)
        self.assertEqual(hidden.status_code, 404)

    def test_memory_reads_and_writes_are_owner_scoped(self) -> None:
        memory_db.add_memory("one", "first", owner_id="user-1")
        memory_db.add_memory("two", "second", owner_id="user-2")

        first = self.client.get("/memory", headers=self.headers("user-1"))
        second = self.client.get("/memory", headers=self.headers("user-2"))
        created = self.client.post(
            "/memory",
            headers=self.headers("user-1"),
            json={"title": "three", "content": "third"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(
            [item["title"] for item in first.json()["memories"]],
            ["one"],
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            [item["title"] for item in second.json()["memories"]],
            ["two"],
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(memory_db.count_memories(owner_id="user-1"), 2)
        self.assertEqual(memory_db.count_memories(owner_id="user-2"), 1)

    def test_attempt_audit_list_and_detail_hide_other_owner(self) -> None:
        first = self.audit_store.append(
            task_id="task-1",
            owner_id="user-1",
            attempt=0,
            event_type="enqueued",
            queue_status="queued",
        )
        second = self.audit_store.append(
            task_id="task-2",
            owner_id="user-2",
            attempt=0,
            event_type="enqueued",
            queue_status="queued",
        )

        listed = self.client.get(
            "/audit/attempts",
            headers=self.headers("user-1"),
        )
        own = self.client.get(
            f"/audit/attempts/{first['audit_id']}",
            headers=self.headers("user-1"),
        )
        hidden = self.client.get(
            f"/audit/attempts/{second['audit_id']}",
            headers=self.headers("user-1"),
        )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["count"], 1)
        self.assertEqual(
            listed.json()["attempts"][0]["audit_id"],
            first["audit_id"],
        )
        self.assertEqual(own.status_code, 200)
        self.assertEqual(hidden.status_code, 404)


if __name__ == "__main__":
    unittest.main()
