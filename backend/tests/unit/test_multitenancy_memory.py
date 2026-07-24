import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.auth import AuthenticatedPrincipal
from app.core.principal_context import reset_current_principal, set_current_principal
from app.database import database, memory_db
from app.memory.memory_manager import (
    add_message,
    clear_history,
    conversation_history,
    get_history,
)


class TestMultiUserMemory(unittest.TestCase):
    def _principal(self, owner_id):
        return AuthenticatedPrincipal(
            owner_id=owner_id,
            authentication_method="test",
        )

    def test_database_memory_is_owner_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "memory.db")
            with patch.object(database, "DATABASE_PATH", path):
                database.initialize_database()
                memory_db.add_memory("one", "first", owner_id="user-1")
                memory_db.add_memory("two", "second", owner_id="user-2")

                first = memory_db.get_all_memories(owner_id="user-1")
                second = memory_db.get_all_memories(owner_id="user-2")

                self.assertEqual([item.title for item in first], ["one"])
                self.assertEqual([item.title for item in second], ["two"])

    def test_legacy_memory_rows_are_backfilled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "legacy.db")
            with sqlite3.connect(path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT,
                        content TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    INSERT INTO memory(title, content)
                    VALUES ('legacy', 'value');
                    """
                )

            with patch.object(database, "DATABASE_PATH", path):
                database.initialize_database()
                rows = memory_db.get_all_memories(owner_id="local-user")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].owner_id, "local-user")


    def test_legacy_conversation_history_alias_stays_live(self):
        clear_history(owner_id="local-user")
        add_message("user", "legacy", owner_id="local-user")

        self.assertEqual(
            conversation_history,
            [{"role": "user", "text": "legacy"}],
        )

    def test_conversation_history_uses_principal_context(self):
        for owner in ("user-1", "user-2"):
            token = set_current_principal(self._principal(owner))
            try:
                clear_history()
                add_message("user", owner)
            finally:
                reset_current_principal(token)

        token = set_current_principal(self._principal("user-1"))
        try:
            self.assertEqual(get_history(), [{"role": "user", "text": "user-1"}])
        finally:
            reset_current_principal(token)

        token = set_current_principal(self._principal("user-2"))
        try:
            self.assertEqual(get_history(), [{"role": "user", "text": "user-2"}])
        finally:
            reset_current_principal(token)


if __name__ == "__main__":
    unittest.main()
