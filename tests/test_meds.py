from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant.db import Database
from assistant.meds_core import due, med_label, nudge_text, streak, taken_text
from tests.test_pc import make_settings

LA = ZoneInfo("America/Los_Angeles")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 18, hour, minute, tzinfo=LA)


class LabelTests(unittest.TestCase):
    def test_from_briefing_and_default(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            settings = make_settings(Path(folder))
            config = {"medication": {"items": [
                {"name": "Wellbutrin", "called": "Happy Pills", "when": "morning"},
                {"name": "Melatonin", "when": "evening"},
            ]}}
            self.assertEqual(med_label(settings, config), "your Happy Pills")
            self.assertEqual(med_label(settings, None), "your morning meds")


class TimingTests(unittest.TestCase):
    def test_due(self) -> None:
        start, until = at(9), at(13)
        self.assertFalse(due(at(8, 59), None, start, until))
        self.assertTrue(due(at(9), None, start, until))
        later = {"nudges": 1, "next_at": at(10).isoformat()}
        self.assertFalse(due(at(9, 30), later, start, until))
        self.assertTrue(due(at(10), later, start, until))
        self.assertFalse(due(at(10), {**later, "taken_at": "x"}, start, until))
        self.assertFalse(due(at(13), None, start, until))

    def test_texts(self) -> None:
        self.assertIn("Good morning", nudge_text(1, "your Happy Pills", False))
        self.assertIn("Last reminder", nudge_text(4, "your Happy Pills", True))
        self.assertIn("Happy Pills", nudge_text(2, "your Happy Pills", False))
        self.assertIn("3-day streak", taken_text(3))


class StreakTests(unittest.TestCase):
    def test_streak_and_store(self) -> None:
        today = date(2026, 11, 18)
        self.assertEqual(streak({"2026-11-18", "2026-11-17", "2026-11-15"}, today), 2)
        self.assertEqual(streak({"2026-11-17"}, today), 0)
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "a.db")
            db.save_meds("2026-11-18", 1, datetime(2026, 11, 18, 18, tzinfo=timezone.utc))
            self.assertEqual(db.get_meds("2026-11-18")["nudges"], 1)
            db.take_meds("2026-11-18")
            db.take_meds("2026-11-17")
            self.assertEqual(db.meds_taken_days(), ["2026-11-18", "2026-11-17"])
            self.assertIsNotNone(db.get_meds("2026-11-18")["taken_at"])
            db.close()


if __name__ == "__main__":
    unittest.main()
