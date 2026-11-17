from __future__ import annotations

import random
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant import memory
from assistant.addons.fun import eight_ball, flip, hero_pick, roll
from assistant.db import Database
from assistant.morning_core import HEROES, fallback, hero_of_the_day, riding_rules, write_hello
from tests.test_pc import make_settings

LA = ZoneInfo("America/Los_Angeles")


class MemoryTests(unittest.TestCase):
    def test_remember_forget(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "about.md"
            self.assertEqual(memory.prompt_block(path), "Nothing saved about Joeii yet.")
            memory.remember("Mains Mercy and Kiriko.", path, datetime(2026, 11, 17))
            self.assertEqual(memory.remember("mains mercy and kiriko", path), "I already knew that.")
            memory.remember("Rides a motorcycle.", path, datetime(2026, 11, 17))
            self.assertEqual(memory.facts(path), ["Mains Mercy and Kiriko. (since Nov 2026)", "Rides a motorcycle. (since Nov 2026)"])
            self.assertIn("never pushed to GitHub", path.read_text())
            self.assertEqual(memory.forget("motorcycle", path), "Forgot 1 thing(s) about Joeii.")
            self.assertEqual(len(memory.facts(path)), 1)

    def test_file_lives_in_ignored_folder(self) -> None:
        ignored = (ROOT / ".gitignore").read_text().split()
        self.assertIn("data/", ignored)
        self.assertEqual(memory.PATH.parent.name, "data")


class FunTests(unittest.TestCase):
    def test_tools(self) -> None:
        rng = random.Random(1)
        self.assertIn("You rolled a", roll("1d20", rng))
        self.assertIn("= **", roll("2d6+3", rng))
        self.assertIn("Try something", roll("lots", rng))
        self.assertIn(flip(rng), ("🪙 **Heads!**", "🪙 **Tails!**"))
        self.assertTrue(eight_ball(rng).startswith("🎱"))
        self.assertIn("(Support)", hero_pick("support", rng))


class MorningTests(unittest.TestCase):
    def test_hero_of_the_day_is_stable(self) -> None:
        day = date(2026, 11, 18)
        self.assertEqual(hero_of_the_day(day), hero_of_the_day(day))
        hero, role = hero_of_the_day(day)
        self.assertIn(hero, HEROES[role])

    def test_riding_rules_from_briefing(self) -> None:
        text = riding_rules({"motorcycle": {"minTemp": 55, "maxPrecipProbability": 20}})
        self.assertIn("at least 55", text)
        self.assertIn("at most 20%", text)

    def test_write_hello_and_fallback(self) -> None:
        facts = {"weather": "Right now in Puyallup: 44 F.", "calendar": "Clear.", "riding": "rules",
                 "reminders": "", "due": "- Essay: due Fri", "hero": "Ana", "role": "Support"}
        with tempfile.TemporaryDirectory() as folder:
            settings = make_settings(Path(folder))
            now = datetime(2026, 11, 18, 8, tzinfo=LA)
            seen = {}

            def fake_agent(settings, system, prompt, tools, call, max_turns):
                seen["prompt"] = prompt
                return "☀️ Good morning, Joeii!"

            with mock.patch("assistant.brain.agent", fake_agent):
                self.assertEqual(write_hello(settings, facts, "- Mains Mercy.", now), "☀️ Good morning, Joeii!")
            self.assertIn("Essay", seen["prompt"])
            self.assertIn("Mains Mercy", seen["prompt"])
            with mock.patch("assistant.brain.agent", side_effect=RuntimeError("down")):
                text = write_hello(settings, facts, "", now)
            self.assertIn("Good morning, Joeii!", text)
            self.assertIn("Due soon", text)
            self.assertNotIn("Today's reminders", text)

    def test_mark_daily_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "a.db")
            self.assertTrue(db.mark_daily("morning", "2026-11-18"))
            self.assertFalse(db.mark_daily("morning", "2026-11-18"))
            self.assertTrue(db.mark_daily("morning", "2026-11-19"))
            db.close()


if __name__ == "__main__":
    unittest.main()
