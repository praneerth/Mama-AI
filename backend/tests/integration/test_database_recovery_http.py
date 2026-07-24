import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import (
    AuthenticatedPrincipal,
    require_database_recovery_administrator,
    require_database_recovery_reader,
)
from app.api.database_recovery import router


class FakeMigrationManager:
    def status(self):
        return {"current_version": 2, "latest_version": 2, "pending": []}


class FakeScheduler:
    def status(self):
        return {"enabled": True, "running": True}


class FakeBackupManager:
    def __init__(self):
        self.backups = []

    def status(self):
        return {
            "database_available": True,
            "integrity": {"ok": True, "mode": "quick", "messages": ["ok"]},
            "backup_count": len(self.backups),
        }

    def list_backups(self, limit=100):
        return self.backups[:limit]

    def create_backup(self, reason, metadata):
        backup = {
            "backup_id": "backup-1",
            "filename": "mama_ai_20260101T000000000000Z_12345678.db",
            "created_at": "2026-01-01T00:00:00+00:00",
            "reason": reason,
            "size_bytes": 100,
            "sha256": "a" * 64,
            "integrity_status": "ok",
            "verified_at": "2026-01-01T00:00:00+00:00",
            "metadata": metadata,
        }
        self.backups = [backup]
        return backup

    def verify_backup(self, filename):
        return {
            "filename": filename,
            "size_bytes": 100,
            "sha256": "a" * 64,
            "integrity_status": "ok",
            "verified_at": "2026-01-01T00:00:00+00:00",
        }

    def prune_backups(self, keep=None):
        return {"kept": keep or 1, "removed": []}


class TestDatabaseRecoveryHTTP(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        principal = AuthenticatedPrincipal(
            owner_id="admin-1",
            authentication_method="test",
            roles=("user", "admin"),
        )
        self.app.dependency_overrides[require_database_recovery_reader] = lambda: principal
        self.app.dependency_overrides[require_database_recovery_administrator] = lambda: principal
        self.fake_backup = FakeBackupManager()
        self.patchers = [
            patch("app.api.database_recovery.backup_manager", self.fake_backup),
            patch("app.api.database_recovery.migration_manager", FakeMigrationManager()),
            patch("app.api.database_recovery.database_recovery_scheduler", FakeScheduler()),
            patch("app.api.database_recovery._record_action", lambda **kwargs: None),
        ]
        for item in self.patchers:
            item.start()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patchers):
            item.stop()

    def test_status_returns_migration_recovery_and_scheduler(self):
        response = self.client.get("/admin/database/status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["migration"]["current_version"], 2)
        self.assertTrue(payload["recovery"]["integrity"]["ok"])
        self.assertTrue(payload["scheduler"]["running"])

    def test_create_list_verify_and_prune_backup(self):
        created = self.client.post(
            "/admin/database/backups",
            json={"reason": "before_upgrade"},
        )
        self.assertEqual(created.status_code, 200)
        filename = created.json()["backup"]["filename"]
        listed = self.client.get("/admin/database/backups")
        self.assertEqual(listed.json()["count"], 1)
        verified = self.client.post(f"/admin/database/backups/{filename}/verify")
        self.assertEqual(verified.status_code, 200)
        pruned = self.client.post("/admin/database/backups/prune?keep=2")
        self.assertEqual(pruned.status_code, 200)
        self.assertEqual(pruned.json()["kept"], 2)

    def test_openapi_marks_every_recovery_endpoint_protected(self):
        schema = self.app.openapi()
        for path, item in schema["paths"].items():
            if not path.startswith("/admin/database"):
                continue
            for method, operation in item.items():
                if method in {"get", "post", "delete", "put", "patch"}:
                    self.assertIn({"HTTPBearer": []}, operation.get("security", []))


if __name__ == "__main__":
    unittest.main()
