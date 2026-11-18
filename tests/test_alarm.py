from __future__ import annotations

import sys
import tempfile
import unittest
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant.alarm_core import (
    MAX_RINGS,
    alarm_rollover,
    beep_wav,
    gave_up,
    ring_text,
    should_ring,
)
from assistant.addons.alarm import Alarms
from assistant.db import Database
from tests.test_pc import make_settings

LA = ZoneInfo("America/Los_Angeles")


class FakeBot:
    def __init__(self, folder: Path):
        self.settings = make_settings(folder)
        self.db = Database(self.settings.database_path)


class CoreTests(unittest.TestCase):
    def test_beep_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = beep_wav(Path(folder) / "alarm.wav")
            with wave.open(str(path)) as audio:
                self.assertGreater(audio.getnframes() / audio.getframerate(), 0.5)

    def test_rollover(self) -> None:
        now = datetime(2026, 11, 18, 16, 0, tzinfo=timezone.utc)  # 8am in LA
        seven = datetime(2026, 11, 18, 7, 0, tzinfo=LA)
        self.assertEqual(alarm_rollover(seven, now), datetime(2026, 11, 19, 7, 0, tzinfo=LA))
        self.assertIsNone(alarm_rollover(seven - timedelta(days=3), now))

    def test_ring_rules(self) -> None:
        now = datetime(2026, 11, 18, 16, 0, tzinfo=timezone.utc)
        self.assertTrue(should_ring({"next_ring_at": None}, now))
        self.assertFalse(should_ring({"next_ring_at": (now + timedelta(seconds=5)).isoformat()}, now))
        self.assertTrue(gave_up({"rings": MAX_RINGS}))
        self.assertIn("wake up", ring_text({"label": "wake up", "rings": 0}))
        self.assertIn("ring 3", ring_text({"label": "", "rings": 2}))


class AlarmFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.bot = FakeBot(Path(self.folder.name))
        self.cog = Alarms(self.bot)

    def tearDown(self) -> None:
        self.bot.db.close()
        self.folder.cleanup()

    def test_set_ring_snooze_stop(self) -> None:
        db = self.bot.db
        text = self.cog.create(42, "in 10 minutes", "wake up")
        self.assertIn("Alarm #1", text)
        self.assertEqual(db.alarms_to_start(datetime.now(timezone.utc)), [])
        later = datetime.now(timezone.utc) + timedelta(minutes=11)
        self.assertEqual(len(db.alarms_to_start(later)), 1)
        db.ring_alarm(1, 0, later)
        self.assertEqual(len(db.ringing_alarms()), 1)
        self.assertIn("Snoozed", self.cog.snooze(1))
        self.assertEqual(db.ringing_alarms(), [])
        db.ring_alarm(1, 3, later)
        self.assertIn("Alarm off", self.cog.stop())
        self.assertEqual(db.get_alarm(1)["state"], "done")
        self.assertEqual(self.cog.stop(), "No alarm is ringing right now.")
        self.assertIn("already off", self.cog.snooze(1))

    def test_now_list_cancel(self) -> None:
        self.cog.create(42, "now")
        self.cog.create(42, "tomorrow at 7am", "class")
        self.assertIn("class", self.cog.listing(42))
        self.assertIn("Cancelled", self.cog.cancel(42, 2))
        self.assertIn("no alarm #2", self.cog.cancel(42, 2))
        self.assertIn("no alarm #1", self.cog.cancel(7, 1))
        self.assertIn("couldn't read", self.cog.create(42, "banana o'clock"))

    def test_tools_exist(self) -> None:
        names = {tool.name for tool in self.cog.assistant_tools()}
        self.assertEqual(names, {"set_alarm", "list_alarms", "stop_alarm", "cancel_alarm"})


if __name__ == "__main__":
    unittest.main()
