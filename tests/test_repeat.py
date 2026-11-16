from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant.db import Database
from assistant.timeparse import describe_every, next_due, parse_every

LA = ZoneInfo("America/Los_Angeles")


class RepeatTests(unittest.TestCase):
    def test_parse_every(self) -> None:
        cases = {
            "30 minutes": 30, "every 30 minutes": 30, "half an hour": 30, "2 hours": 120,
            "hourly": 60, "day": 1440, "daily": 1440, "every week": 10080, "an hour": 60,
            "90 min": 90, "1.5 hours": 90,
        }
        for text, minutes in cases.items():
            self.assertEqual(parse_every(text), minutes, text)
        for bad in ("soon", "0 minutes", "every fortnight", ""):
            with self.assertRaises(ValueError):
                parse_every(bad)

    def test_describe(self) -> None:
        self.assertEqual(describe_every(30), "every 30 minutes")
        self.assertEqual(describe_every(120), "every 2 hours")
        self.assertEqual(describe_every(1440), "every day")

    def test_next_due_skips_missed(self) -> None:
        due = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
        now = datetime(2026, 11, 15, 11, 10, tzinfo=timezone.utc)
        self.assertEqual(next_due(due, 30, LA, now), datetime(2026, 11, 15, 11, 30, tzinfo=timezone.utc))

    def test_daily_keeps_local_time_over_dst(self) -> None:
        # 9am Los Angeles on Saturday March 7 2026; clocks spring forward on the 8th.
        due = datetime(2026, 3, 7, 9, 0, tzinfo=LA).astimezone(timezone.utc)
        upcoming = next_due(due, 1440, LA, due)
        self.assertEqual(upcoming.astimezone(LA).hour, 9)
        self.assertEqual(upcoming.astimezone(LA).day, 8)


class StorageTests(unittest.TestCase):
    def test_old_database_gets_new_columns(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            conn = sqlite3.connect(path)
            conn.execute(
                "CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
                "text TEXT NOT NULL, due_at TEXT NOT NULL, created_at TEXT NOT NULL, "
                "sent INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0)"
            )
            conn.commit()
            conn.close()
            db = Database(path)
            due = datetime(2030, 1, 1, tzinfo=timezone.utc)
            row = db.add_reminder(1, "list the nerf", due, 30)
            self.assertEqual(row["repeat_minutes"], 30)
            later = datetime(2030, 1, 1, 0, 30, tzinfo=timezone.utc)
            db.reschedule_reminder(row["id"], later)
            self.assertEqual(db.list_reminders(1)[0]["due_at"], later.isoformat())
            db.close()


if __name__ == "__main__":
    unittest.main()
