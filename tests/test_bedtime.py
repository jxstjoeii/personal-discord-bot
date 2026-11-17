from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, time
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant import bedtime_core
from assistant.bedtime_core import FALLBACK, current_slot, night_window, parse_clock, write_nudge
from assistant.db import Database
from tests.test_pc import make_settings

LA = ZoneInfo("America/Los_Angeles")
START, END = time(20, 30), time(4, 0)


class ClockTests(unittest.TestCase):
    def test_parse(self) -> None:
        self.assertEqual(parse_clock("20:30"), time(20, 30))
        self.assertEqual(parse_clock("8:30pm"), time(20, 30))
        self.assertEqual(parse_clock("8:30 PM"), time(20, 30))
        self.assertEqual(parse_clock("12am"), time(0, 0))
        self.assertEqual(parse_clock("4"), time(4, 0))
        for bad in ("25:00", "13pm", "soon"):
            with self.assertRaises(ValueError):
                parse_clock(bad)


class WindowTests(unittest.TestCase):
    def slot(self, *args):
        now = datetime(*args, tzinfo=LA)
        night, start_at, end_at = night_window(now, START, END)
        return night.isoformat(), current_slot(now, start_at, end_at, 30)

    def test_slots(self) -> None:
        self.assertEqual(self.slot(2026, 11, 16, 20, 0), ("2026-11-16", None))
        self.assertEqual(self.slot(2026, 11, 16, 20, 30), ("2026-11-16", 0))
        self.assertEqual(self.slot(2026, 11, 16, 20, 59), ("2026-11-16", 0))
        self.assertEqual(self.slot(2026, 11, 16, 21, 0), ("2026-11-16", 1))
        # After midnight still belongs to Monday night.
        self.assertEqual(self.slot(2026, 11, 17, 1, 15), ("2026-11-16", 9))
        self.assertEqual(self.slot(2026, 11, 17, 4, 0), ("2026-11-17", None))


class StoreTests(unittest.TestCase):
    def test_save_and_finish(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "a.db")
            self.assertIsNone(db.get_bedtime("2026-11-16"))
            db.save_bedtime("2026-11-16", 0, ["Time for bed."])
            db.save_bedtime("2026-11-16", 1, ["Time for bed.", "Really."])
            row = db.get_bedtime("2026-11-16")
            self.assertEqual(row["last_slot"], 1)
            self.assertIsNone(row["done_at"])
            db.finish_bedtime("2026-11-16")
            self.assertIsNotNone(db.get_bedtime("2026-11-16")["done_at"])
            db.finish_bedtime("2026-11-17")
            self.assertIsNotNone(db.get_bedtime("2026-11-17")["done_at"])
            db.close()


class NudgeTests(unittest.TestCase):
    def test_uses_claude_and_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            settings = make_settings(Path(folder))
            now = datetime(2026, 11, 16, 21, 0, tzinfo=LA)
            seen = {}

            def fake_agent(settings, system, prompt, tools, call, max_turns):
                seen["system"], seen["prompt"] = system, prompt
                return '"Time to wind down, Joeii. Save the game and go brush your teeth."'

            with mock.patch("assistant.brain.agent", fake_agent):
                text = write_nudge(settings, 2, now, ["It's 8:30, start getting ready."])
            self.assertEqual(text, "Time to wind down, Joeii. Save the game and go brush your teeth.")
            self.assertIn("firm but kind", seen["system"].lower())
            self.assertIn("9:00 PM", seen["prompt"])
            self.assertIn("8:30 PM", seen["prompt"])
            self.assertIn("It's 8:30, start getting ready.", seen["prompt"])

            with mock.patch("assistant.brain.agent", side_effect=RuntimeError("limit")):
                self.assertEqual(write_nudge(settings, 99, now, []), FALLBACK[-1])


if __name__ == "__main__":
    unittest.main()
