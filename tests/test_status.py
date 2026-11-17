from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant.status_core import POOLS, next_line, pick_mood

LA = ZoneInfo("America/Los_Angeles")


def at(hour: int) -> datetime:
    return datetime(2026, 11, 16, hour, 0, tzinfo=LA)


class MoodTests(unittest.TestCase):
    def test_priority(self) -> None:
        self.assertEqual(pick_mood(at(22), in_bedtime=False, bedtime_done=True, gaming=True), "asleep")
        self.assertEqual(pick_mood(at(22), in_bedtime=True, bedtime_done=False, gaming=True), "bedtime")
        self.assertEqual(pick_mood(at(15), in_bedtime=False, bedtime_done=False, gaming=True), "overwatch")

    def test_time_of_day(self) -> None:
        self.assertEqual(pick_mood(at(7), in_bedtime=False, bedtime_done=False, gaming=False), "morning")
        self.assertEqual(pick_mood(at(13), in_bedtime=False, bedtime_done=False, gaming=False), "day")
        self.assertEqual(pick_mood(at(19), in_bedtime=False, bedtime_done=False, gaming=False), "evening")
        self.assertEqual(pick_mood(at(2), in_bedtime=False, bedtime_done=False, gaming=False), "evening")

    def test_rotation_cycles_without_repeats(self) -> None:
        line = None
        seen = []
        for _ in range(len(POOLS["day"]) + 1):
            line = next_line("day", line)
            seen.append(line)
        self.assertEqual(seen[0], seen[-1])
        self.assertEqual(len(set(seen[:-1])), len(POOLS["day"]))
        self.assertTrue(all(len(item) <= 128 for pool in POOLS.values() for item in pool))


if __name__ == "__main__":
    unittest.main()
