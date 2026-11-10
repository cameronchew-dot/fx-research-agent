import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ops.research_storage_backup import backup_database


class ResearchStorageBackupTests(unittest.TestCase):
    def test_backup_is_verified_and_retains_latest_three(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "research.sqlite3"
            backups = root / "backups"
            with sqlite3.connect(db) as connection:
                connection.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY)")
                connection.execute("INSERT INTO observations DEFAULT VALUES")

            for day in range(1, 5):
                result = backup_database(
                    db,
                    backups,
                    retain=3,
                    now=datetime(2026, 1, day, tzinfo=timezone.utc),
                )

            retained = sorted(backups.glob("fx_research_agent_*.sqlite3"))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["retained_backup_count"], 3)
            self.assertEqual(len(retained), 3)
            self.assertNotIn("20260101", retained[0].name)
            for path in retained:
                with sqlite3.connect(path) as connection:
                    self.assertEqual(
                        connection.execute("PRAGMA integrity_check").fetchone()[0],
                        "ok",
                    )


if __name__ == "__main__":
    unittest.main()
