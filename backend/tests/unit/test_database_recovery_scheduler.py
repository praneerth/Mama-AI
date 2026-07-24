import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.config import settings
from app.database.recovery_scheduler import DatabaseRecoveryScheduler


class FakeBackupManager:
    def __init__(self, backups=None):
        self.backups = list(backups or [])
        self.created = 0

    def list_backups(self, limit=100):
        return self.backups[:limit]

    def create_backup(self, **kwargs):
        self.created += 1
        result = {
            "backup_id": f"id-{self.created}",
            "filename": f"backup-{self.created}.db",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.backups.insert(0, result)
        return result


class TestDatabaseRecoveryScheduler(unittest.TestCase):
    def test_run_if_due_creates_when_no_backup_exists(self):
        manager = FakeBackupManager()
        scheduler = DatabaseRecoveryScheduler(manager)
        with patch.object(settings, "DATABASE_BACKUP_MIN_INTERVAL_SECONDS", 3600):
            result = scheduler.run_if_due()
        self.assertTrue(result["created"])
        self.assertEqual(manager.created, 1)

    def test_recent_backup_skips_creation(self):
        manager = FakeBackupManager([
            {"created_at": datetime.now(timezone.utc).isoformat()}
        ])
        scheduler = DatabaseRecoveryScheduler(manager)
        with patch.object(settings, "DATABASE_BACKUP_MIN_INTERVAL_SECONDS", 3600):
            result = scheduler.run_if_due()
        self.assertFalse(result["created"])
        self.assertEqual(result["reason"], "minimum_interval")
        self.assertEqual(manager.created, 0)

    def test_disabled_scheduler_does_not_start(self):
        scheduler = DatabaseRecoveryScheduler(FakeBackupManager())
        with patch.object(settings, "DATABASE_BACKUP_ENABLED", False):
            result = scheduler.start()
        self.assertFalse(result["started"])
        self.assertFalse(scheduler.running)

    def test_scheduler_starts_and_stops_cleanly(self):
        scheduler = DatabaseRecoveryScheduler(FakeBackupManager())
        with patch.object(settings, "DATABASE_BACKUP_ENABLED", True), patch.object(
            settings, "DATABASE_BACKUP_ON_STARTUP", False
        ), patch.object(settings, "DATABASE_BACKUP_INTERVAL_SECONDS", 60):
            started = scheduler.start()
            stopped = scheduler.stop()
        self.assertTrue(started["started"])
        self.assertTrue(stopped["stopped"])


if __name__ == "__main__":
    unittest.main()
