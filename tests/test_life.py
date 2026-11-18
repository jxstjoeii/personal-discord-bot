from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant import pc_controls
from assistant.db import Database
from assistant.life_core import (
    birthday_line,
    birthday_message,
    mood_reply,
    next_birthday,
    parse_birthday,
    upcoming_birthdays,
)
from assistant.recap_core import day_facts, fallback_day, fallback_week, week_facts, write
from tests.test_pc import make_settings

LA = ZoneInfo("America/Los_Angeles")


class QuickControlTests(unittest.TestCase):
    def test_matches(self) -> None:
        cases = {
            "volume down": ("volume_down", None),
            "(said out loud) Turn the volume up.": ("volume_up", None),
            "set volume to 30%": ("set_volume", 30),
            "volume up by 20": ("volume_up", 20),
            "mute": ("mute", None),
            "pause the music please": ("play_pause", None),
            "skip song": ("next_track", None),
            "next track": ("next_track", None),
            "previous song": ("previous_track", None),
            "Lock my PC": ("lock", None),
            "turn off my screens": ("screens_off", None),
            "can you mute": ("mute", None),
        }
        for text, expected in cases.items():
            self.assertEqual(pc_controls.quick(text), expected, text)

    def test_leaves_real_questions_alone(self) -> None:
        for text in ("why does my music pause when I alt tab", "what's the weather", "play overwatch with me",
                     "remind me to lock my bike tomorrow"):
            self.assertIsNone(pc_controls.quick(text), text)

    def test_run_off_windows(self) -> None:
        if not pc_controls.pc.is_windows():
            self.assertIn("only work on the Windows PC", pc_controls.run("mute"))


class MoodTests(unittest.TestCase):
    def test_replies(self) -> None:
        self.assertIn("rough", mood_reply(1, [1]))
        self.assertIn("great day", mood_reply(5, [5]))
        self.assertIn("few hard days", mood_reply(2, [2, 1, 2]))
        self.assertNotIn("few hard days", mood_reply(2, [4, 1, 2]))

    def test_store(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "a.db")
            db.save_mood("2026-11-16", 2, "")
            db.save_mood("2026-11-17", 4, "good practice")
            db.save_mood("2026-11-17", 5, "good practice")
            rows = db.moods_since("2026-11-17")
            self.assertEqual([(r["score"], r["note"]) for r in rows], [(5, "good practice")])
            db.close()


class BirthdayTests(unittest.TestCase):
    def test_parse(self) -> None:
        self.assertEqual(parse_birthday("March 3"), (3, 3, None))
        self.assertEqual(parse_birthday("3rd of march, 2004"), (3, 3, 2004))
        self.assertEqual(parse_birthday("Sept 14"), (9, 14, None))
        self.assertEqual(parse_birthday("12/25/2001"), (12, 25, 2001))
        self.assertEqual(parse_birthday("2/29"), (2, 29, None))
        for bad in ("soon", "2/30", "13/1"):
            with self.assertRaises(ValueError):
                parse_birthday(bad)

    def test_next_and_lines(self) -> None:
        today = date(2026, 11, 17)
        self.assertEqual(next_birthday(11, 17, today), today)
        self.assertEqual(next_birthday(3, 3, today), date(2027, 3, 3))
        self.assertEqual(next_birthday(2, 29, date(2027, 1, 1)), date(2027, 2, 28))
        row = {"id": 1, "name": "Syl", "month": 11, "day": 20, "year": 2004, "note": ""}
        self.assertEqual(birthday_line(row, today), "Syl: in 3 days (Fri, Nov 20), turning 22")
        self.assertIn("in 3 days", birthday_message(row, today, 3))
        self.assertIn("Today is **Syl**", birthday_message({**row, "day": 17}, today, 0))
        soon = upcoming_birthdays([row, {**row, "id": 2, "name": "Far", "month": 6}], today, 7)
        self.assertEqual([r["name"] for r in soon], ["Syl"])

    def test_store(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "a.db")
            db.add_birthday("Syl", 3, 3, None, "")
            db.add_birthday("syl", 3, 4, 2004, "likes Overwatch merch")
            self.assertEqual(len(db.list_birthdays()), 1)
            self.assertEqual(db.list_birthdays()[0]["day"], 4)
            self.assertEqual(db.remove_birthday("Syl"), "Syl")
            self.assertEqual(db.remove_birthday("nobody"), "")
            db.close()


class RecapTests(unittest.TestCase):
    def test_day_and_week(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "a.db")
            now = datetime(2026, 11, 17, 21, 30, tzinfo=LA)
            start_utc = datetime(2026, 11, 17, 0, 0, tzinfo=LA).astimezone(timezone.utc)
            essay = db.add_assignment(1, "Essay", "", "", now.astimezone(timezone.utc) - timedelta(hours=2))
            db.add_assignment(1, "Bio quiz", "", "", (now + timedelta(hours=14)).astimezone(timezone.utc))
            with mock.patch("assistant.db.datetime") as fake:
                fake.now.return_value = start_utc + timedelta(hours=18)
                fake.fromisoformat = datetime.fromisoformat
                db.complete_assignment(1, essay["id"])
            db.take_meds("2026-11-17")
            db.take_meds("2026-11-16")
            db.save_mood("2026-11-17", 4, "")
            db.start_game_session("Overwatch", start_utc + timedelta(hours=19))
            row = db.open_game_session()
            db.touch_game_session(row["id"], start_utc + timedelta(hours=20, minutes=30))
            db.end_game_session(row["id"], start_utc + timedelta(hours=20, minutes=30))
            db.add_birthday("Syl", 11, 19, None, "")
            facts = day_facts(db, 1, LA, now, {"weather_tomorrow": "Rain."})
            self.assertEqual(facts["done"], ["Essay"])
            self.assertTrue(facts["due_tomorrow"][0].startswith("Bio quiz"))
            self.assertEqual(facts["meds"], "taken, streak 2 day(s)")
            self.assertEqual(facts["played"], "1h 30m")
            self.assertEqual(facts["mood"], "4/5")
            self.assertEqual(facts["birthdays"], ["Syl: in 2 days (Thu, Nov 19)"])
            text = fallback_day(facts)
            for words in ("Finished: Essay", "Played: 1h 30m", "Bio quiz", "Good night"):
                self.assertIn(words, text)
            week = week_facts(db, 1, LA, now)
            self.assertEqual(week["meds"], "2 of 2 days, current streak 2")
            self.assertEqual(week["sessions"], 1)
            self.assertIn("Your week", fallback_week(week))
            settings = make_settings(Path(folder))
            seen = {}

            def fake_agent(settings, system, prompt, tools, call, max_turns):
                seen["prompt"] = prompt
                return "🌙 Nice work today, Joeii!"

            with mock.patch("assistant.brain.agent", fake_agent):
                self.assertEqual(write(settings, "day", facts, "- Mains Mercy."), "🌙 Nice work today, Joeii!")
            self.assertIn("weather_tomorrow: Rain.", seen["prompt"])
            self.assertIn("done:\n- Essay", seen["prompt"])
            db.close()


if __name__ == "__main__":
    unittest.main()
