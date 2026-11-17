from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant import assignments_core
from assistant.assignments_core import checkpoints, message, parse_due, pending
from assistant.db import Database

LA = ZoneInfo("America/Los_Angeles")


def local(*args) -> datetime:
    return datetime(*args, tzinfo=LA)


def utc(*args) -> datetime:
    return local(*args).astimezone(timezone.utc)


class DueTests(unittest.TestCase):
    def test_day_alone_means_end_of_day(self) -> None:
        now = local(2026, 11, 17, 13, 0)
        with mock.patch.object(assignments_core, "parse_when", return_value=utc(2026, 11, 20, 13, 0)):
            self.assertEqual(parse_due("friday", LA, now).astimezone(LA), local(2026, 11, 20, 23, 59))
            self.assertEqual(parse_due("friday 3pm", LA, now), utc(2026, 11, 20, 13, 0))
            self.assertEqual(parse_due("friday at 15:00", LA, now), utc(2026, 11, 20, 13, 0))


class CheckpointTests(unittest.TestCase):
    def test_full_set_for_late_deadline(self) -> None:
        points = checkpoints(utc(2026, 11, 20, 23, 59), LA)
        keys = [key for key, _ in points]
        self.assertEqual(keys, ["3d", "1d", "morning", "2h", "overdue"])
        times = dict((key, moment.astimezone(LA)) for key, moment in points)
        self.assertEqual(times["3d"], local(2026, 11, 17, 17, 0))
        self.assertEqual(times["1d"], local(2026, 11, 19, 17, 0))
        self.assertEqual(times["morning"], local(2026, 11, 20, 8, 0))
        self.assertEqual(times["2h"], local(2026, 11, 20, 21, 59))

    def test_early_deadline_skips_two_hour(self) -> None:
        keys = [key for key, _ in checkpoints(utc(2026, 11, 20, 9, 0), LA)]
        self.assertEqual(keys, ["3d", "1d", "morning", "overdue"])

    def test_pending_skips_old_and_pre_creation(self) -> None:
        due = utc(2026, 11, 20, 23, 59)
        created = utc(2026, 11, 18, 12, 0)  # after the 3-day reminder time
        self.assertIsNone(pending(due, LA, [], utc(2026, 11, 18, 18, 0), created))
        self.assertEqual(pending(due, LA, [], utc(2026, 11, 19, 17, 1), created), "1d")
        self.assertIsNone(pending(due, LA, ["1d"], utc(2026, 11, 19, 18, 0), created))
        # Offline all day: only the newest one goes out, and stale ones are skipped.
        self.assertEqual(pending(due, LA, [], utc(2026, 11, 20, 22, 0), created), "2h")
        self.assertEqual(pending(due, LA, ["2h"], utc(2026, 11, 22, 9, 0), created), "overdue")

    def test_message(self) -> None:
        text = message("1d", "History essay", "HIST 101", "Fri, Nov 20 at 11:59 PM")
        self.assertIn("**History essay** (HIST 101)", text)
        self.assertIn("tomorrow", text)


class StoreTests(unittest.TestCase):
    def test_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "a.db")
            due = datetime(2030, 1, 5, tzinfo=timezone.utc)
            row = db.add_assignment(1, "Essay", "HIST", "", due)
            db.add_assignment(1, "Quiz", "", "", due - timedelta(days=2))
            self.assertEqual([r["title"] for r in db.list_assignments(1)], ["Quiz", "Essay"])
            db.mark_assignment_sent(row["id"], ["3d"])
            moved = db.move_assignment(1, row["id"], due + timedelta(days=1))
            self.assertEqual(moved["sent"], "[]")
            self.assertIsNotNone(db.complete_assignment(1, row["id"]))
            self.assertIsNone(db.complete_assignment(1, row["id"]))
            self.assertEqual([r["title"] for r in db.open_assignments()], ["Quiz"])
            self.assertIsNotNone(db.remove_assignment(1, db.list_assignments(1)[0]["id"]))
            db.close()


if __name__ == "__main__":
    unittest.main()
