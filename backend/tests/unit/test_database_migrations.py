import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database.migrations import (
    DEFAULT_MIGRATIONS,
    MIGRATION_ROLLBACK_CONFIRMATION,
    Migration,
    MigrationChecksumError,
    MigrationManager,
    MigrationRollbackError,
    MigrationVersionError,
)


class TestDatabaseMigrations(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "migration.db"

    def tearDown(self):
        self.temp.cleanup()

    def test_migrations_apply_once_and_report_status(self):
        manager = MigrationManager(self.path)
        first = manager.migrate()
        second = manager.migrate()
        status = manager.status()
        self.assertEqual([item["version"] for item in first["applied"]], [1, 2])
        self.assertEqual(second["applied"], [])
        self.assertEqual(status["current_version"], 2)
        self.assertEqual(status["pending"], [])

    def test_checksum_drift_fails_closed(self):
        MigrationManager(self.path).migrate()
        changed = (
            Migration(
                version=1,
                name=DEFAULT_MIGRATIONS[0].name,
                statements=("CREATE TABLE changed_schema(id INTEGER)",),
            ),
            DEFAULT_MIGRATIONS[1],
        )
        with self.assertRaises(MigrationChecksumError):
            MigrationManager(self.path, changed).status()

    def test_unknown_future_version_is_rejected(self):
        manager = MigrationManager(self.path)
        manager.migrate()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO schema_migrations(version, name, checksum, execution_ms) VALUES (99, 'future', 'x', 0)")
        with self.assertRaises(MigrationVersionError):
            manager.status()

    def test_reversible_latest_migration_can_be_rolled_back(self):
        manager = MigrationManager(self.path)
        manager.migrate()
        result = manager.rollback_last(confirmation=MIGRATION_ROLLBACK_CONFIRMATION)
        self.assertEqual(result["version"], 2)
        self.assertEqual(manager.status()["current_version"], 1)

    def test_rollback_requires_exact_confirmation(self):
        manager = MigrationManager(self.path)
        manager.migrate()
        with self.assertRaises(MigrationRollbackError):
            manager.rollback_last(confirmation="wrong")

    def test_irreversible_migration_refuses_rollback(self):
        manager = MigrationManager(self.path)
        manager.migrate()
        manager.rollback_last(confirmation=MIGRATION_ROLLBACK_CONFIRMATION)
        with self.assertRaises(MigrationRollbackError):
            manager.rollback_last(confirmation=MIGRATION_ROLLBACK_CONFIRMATION)


if __name__ == "__main__":
    unittest.main()
