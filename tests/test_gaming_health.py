from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant.db import Database
from assistant.gaming_core import duration_text, total_minutes, week_start, wrap_up
from assistant.health_core import log_problems, report

LA = ZoneInfo("America/Los_Angeles")


class GamingTests(unittest.TestCase):
    def test_duration_and_week(self) -> None:
        self.assertEqual(duration_text(135), "2h 15m")
        self.assertEqual(duration_text(60), "1h")
        self.assertEqual(duration_text(9.6), "10m")
        monday = week_start(datetime(2026, 11, 18, 21, tzinfo=LA))
        self.assertEqual((monday.day, monday.hour), (16, 0))

    def test_totals_and_store(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "a.db")
            start = datetime(2026, 11, 18, 3, 0, tzinfo=timezone.utc)
            db.start_game_session("Overwatch", start)
            row = db.open_game_session()
            db.touch_game_session(row["id"], start + timedelta(minutes=90))
            db.end_game_session(row["id"], start + timedelta(minutes=90))
            self.assertIsNone(db.open_game_session())
            db.start_game_session("Overwatch", start + timedelta(hours=3))
            now = start + timedelta(hours=3, minutes=30)
            sessions = db.game_sessions_since(start - timedelta(days=1))
            self.assertEqual(round(total_minutes(sessions, start - timedelta(days=1), now)), 120)
            # Only the part after "since" counts.
            self.assertEqual(round(total_minutes(sessions, start + timedelta(minutes=60), now)), 60)
            db.close()

    def test_wrap_up(self) -> None:
        start = datetime(2026, 11, 18, 19, 10, tzinfo=LA)
        text = wrap_up("Overwatch", start, start + timedelta(minutes=135), 340, True, "kept")
        self.assertIn("**2h 15m** (7:10 PM to 9:25 PM)", text)
        self.assertIn("5h 40m this week", text)
        self.assertIn("kept your one-more-game promise", text)
        self.assertIn("winding down", text)


class HealthTests(unittest.TestCase):
    def test_report(self) -> None:
        good = {"disks": [{"name": "C:", "freeGb": 400, "sizeGb": 1000}], "pendingUpdates": 0,
                "rebootPending": False, "uptimeDays": 2, "startupTask": "Running",
                "tailscale": "Running", "tailscaleOnline": True}
        self.assertIn("all good", report(good, 0))
        bad = {**good, "disks": [{"name": "C:", "freeGb": 15, "sizeGb": 500}], "rebootPending": True,
               "startupTask": "missing", "tailscale": "Stopped", "uptimeDays": 20}
        text = report(bad, 3)
        for words in ("clear some space", "needs a restart", "install-startup", "Remote Desktop from school won't work",
                      "hasn't restarted in 20", "3 error(s)"):
            self.assertIn(words, text)
        self.assertIn("only works on the Windows PC", report({}, 0))

    def test_log_problems(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "bot.log"
            log.write_text(
                "2026-11-01 10:00:00,000 ERROR old: x\n"
                "2026-11-16 10:00:00,000 ERROR assistant.app: boom\n"
                "2026-11-16 10:00:01,000 INFO assistant.app: fine\n",
                encoding="utf-8",
            )
            self.assertEqual(log_problems(log, datetime(2026, 11, 17)), 1)


if __name__ == "__main__":
    unittest.main()
