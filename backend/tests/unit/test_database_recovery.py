import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.recovery import (
    BackupIntegrityError,
    BackupManager,
    BackupNotFoundError,
    RESTORE_CONFIRMATION,
    RestoreConfirmationError,
    run_integrity_check,
)


class TestDatabaseRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "runtime.db"
        self.backups = self.root / "backups"
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE values_table(value TEXT NOT NULL)")
            connection.execute("INSERT INTO values_table(value) VALUES ('original')")
        self.manager = BackupManager(
            self.database,
            self.backups,
            retention_count=3,
            integrity_mode="quick",
        )

    def tearDown(self):
        self.temp.cleanup()

    def _read_value(self):
        with sqlite3.connect(self.database) as connection:
            return connection.execute("SELECT value FROM values_table").fetchone()[0]

    def test_backup_is_created_with_checksum_and_sidecar(self):
        result = self.manager.create_backup(reason="unit_test")
        path = self.backups / result["filename"]
        self.assertTrue(path.exists())
        self.assertTrue(path.with_suffix(".db.json").exists())
        self.assertEqual(result["integrity_status"], "ok")
        self.assertEqual(len(result["sha256"]), 64)

    def test_backup_verification_detects_tampering(self):
        result = self.manager.create_backup(reason="tamper_test")
        path = self.backups / result["filename"]
        with path.open("ab") as handle:
            handle.write(b"tampered")
        with self.assertRaises(BackupIntegrityError):
            self.manager.verify_backup(result["filename"])

    def test_retention_removes_old_backups(self):
        manager = BackupManager(self.database, self.backups, retention_count=2)
        for index in range(4):
            manager.create_backup(reason=f"retention-{index}")
        self.assertEqual(len(manager.list_backups(limit=100)), 2)

    def test_restore_requires_confirmation_and_restores_data(self):
        backup = self.manager.create_backup(reason="restore_source", apply_retention=False)
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE values_table SET value = 'changed'")
        with self.assertRaises(RestoreConfirmationError):
            self.manager.restore_backup(backup["filename"], confirmation="wrong")
        result = self.manager.restore_backup(
            backup["filename"],
            confirmation=RESTORE_CONFIRMATION,
        )
        self.assertTrue(result["restored"])
        self.assertEqual(self._read_value(), "original")
        self.assertIsNotNone(result["pre_restore_backup"])

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(BackupNotFoundError):
            self.manager.verify_backup("../runtime.db")

    def test_integrity_check_reports_corruption(self):
        broken = self.root / "broken.db"
        broken.write_bytes(b"not sqlite")
        result = run_integrity_check(broken)
        self.assertFalse(result["ok"])

    def test_list_does_not_expose_filesystem_paths(self):
        self.manager.create_backup(reason="safe_listing")
        listing = self.manager.list_backups()
        self.assertEqual(len(listing), 1)
        self.assertNotIn("path", listing[0])
        self.assertNotIn(str(self.root), repr(listing[0]))


if __name__ == "__main__":
    unittest.main()
