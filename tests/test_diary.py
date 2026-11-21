from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant.db import Database
from assistant.diary_core import PROMPTS, clean_entry, format_entries, parse_day, prompt_card, prompts_for

LA = ZoneInfo("America/Los_Angeles")
TODAY = date(2026, 11, 20)  # a Friday


class ParseDayTests(unittest.TestCase):
    def test_words_and_dates(self) -> None:
        cases = {
            "": TODAY,
            "today": TODAY,
            "Yesterday": date(2026, 11, 19),
            "3 days ago": date(2026, 11, 17),
            "monday": date(2026, 11, 16),
            "last friday": date(2026, 11, 13),
            "2026-11-02": date(2026, 11, 2),
            "11/18": date(2026, 11, 18),
            "nov 1": date(2026, 11, 1),
            "dec 25": date(2025, 12, 25),  # never in the future
        }
        for text, expected in cases.items():
            self.assertEqual(parse_day(text, TODAY), expected, text)

    def test_bad_date(self) -> None:
        with self.assertRaises(ValueError):
            parse_day("banana", TODAY)


class PromptTests(unittest.TestCase):
    def test_same_all_day_and_short(self) -> None:
        self.assertEqual(prompts_for("2026-11-20"), prompts_for("2026-11-20"))
        self.assertEqual(len(set(prompts_for("2026-11-20", 3))), 3)
        for question in PROMPTS:
            self.assertLess(len(question), 100)  # fits the placeholder in the writing box
        card = prompt_card("2026-11-20")
        self.assertIn("Stuck on a word?", card)

    def test_clean(self) -> None:
        self.assertEqual(clean_entry("  had   a good day\n\n\n\nok  "), "had a good day\n\nok")
        self.assertEqual(len(clean_entry("a" * 9000)), 4000)


class DiaryStoreTests(unittest.TestCase):
    def test_save_read_search_delete(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "data" / "assistant.db")
            first = db.add_diary("2026-11-19", "Rode to campus, the bike felt great.")
            db.add_diary("2026-11-20", "Bio quiz went okay. Played comp with Syl.", "What made you smile today?")
            db.add_diary("2026-11-20", "Feeling tired but proud.")
            self.assertEqual(len(db.diary_between("2026-11-20", "2026-11-20")), 2)
            self.assertEqual(len(db.diary_between("2026-11-14", "2026-11-20")), 3)
            self.assertEqual([r["day"] for r in db.search_diary("syl")], ["2026-11-20"])
            self.assertEqual(db.search_diary("smile")[0]["prompt"], "What made you smile today?")
            self.assertEqual(db.diary_days()[0], {"day": "2026-11-20", "entries": 2})
            text = format_entries(db.diary_between("2026-11-19", "2026-11-20"), LA)
            self.assertIn("Thursday, Nov 19, 2026", text)
            self.assertIn("Friday, Nov 20, 2026", text)
            self.assertIn(f"(#{first['id']})", text)
            self.assertEqual(db.delete_diary(first["id"])["day"], "2026-11-19")
            self.assertIsNone(db.delete_diary(first["id"]))
            db.close()


class DiaryAddonTests(unittest.TestCase):
    def test_tools_save_and_read(self) -> None:
        from assistant.addons.diary import Diary

        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / "assistant.db")
            bot = SimpleNamespace(db=db, settings=SimpleNamespace(timezone=LA, owner_id=1))
            cog = Diary(bot)
            tools = {tool.name: tool for tool in cog.assistant_tools()}
            self.assertEqual(set(tools), {"save_diary_entry", "read_diary", "diary_prompts"})
            self.assertIn("Saved in your diary for today", tools["save_diary_entry"].handler(None, text="Good day."))
            self.assertIn("Saved in your diary for", tools["save_diary_entry"].handler(None, text="Rainy.", day="yesterday"))
            self.assertIn("Good day.", tools["read_diary"].handler(None, day="today"))
            self.assertIn("Rainy.", tools["read_diary"].handler(None, days=7))
            self.assertIn("Nothing in your diary mentions", tools["read_diary"].handler(None, search="zebra"))
            self.assertIn("nothing to save", cog.save_entry("   "))
            self.assertIn("couldn't tell", cog.save_entry("hi", "banana"))
            db.close()


if __name__ == "__main__":
    unittest.main()
