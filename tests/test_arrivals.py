from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from assistant.addons.arrivals import Arrivals
from assistant.arrivals_core import is_repeat, parse_ping, ping_text, place_key
from assistant.db import Database
from tests.test_pc import make_settings

NOW = datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc)


class ParseTests(unittest.TestCase):
    def test_pings(self) -> None:
        self.assertEqual(parse_ping("arrive school"), ("arrive", "school"))
        self.assertEqual(parse_ping("Arrived at Home!"), ("arrive", "Home"))
        self.assertEqual(parse_ping("left: the gym"), ("leave", "the gym"))
        self.assertEqual(parse_ping("Patricia, leaving work"), ("leave", "work"))
        self.assertIsNone(parse_ping("hello there"))
        self.assertIsNone(parse_ping("arrive"))
        self.assertIsNone(parse_ping(""))

    def test_keys(self) -> None:
        self.assertEqual(place_key("  My  House! "), "my house")
        self.assertEqual(ping_text("arrive", "My House"), "arrive my house")

    def test_repeat(self) -> None:
        self.assertFalse(is_repeat(None, NOW))
        self.assertTrue(is_repeat((NOW - timedelta(minutes=5)).isoformat(), NOW))
        self.assertFalse(is_repeat((NOW - timedelta(minutes=30)).isoformat(), NOW))


class FakeBot:
    def __init__(self, folder: Path):
        self.settings = make_settings(folder)
        self.db = Database(folder / "a.db")
        self.sent: list[str] = []
        owner = SimpleNamespace(send=self._send)
        self.get_user = lambda _id: owner

    async def _send(self, text: str) -> None:
        self.sent.append(text)


class HandleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.bot = FakeBot(Path(self._dir.name))
        self.cog = Arrivals(self.bot)

    def tearDown(self) -> None:
        self.bot.db.close()
        self._dir.cleanup()

    def run_ping(self, kind: str, place: str, now: datetime = NOW, held: bool = False) -> str:
        async def holding() -> bool:
            return held

        with mock.patch.object(self.cog, "_holding", holding):
            return asyncio.run(self.cog.handle_ping(kind, place, now))

    def test_send_repeat_and_leave(self) -> None:
        reply = self.cog.set_message("School", "Park in lot B")
        self.assertIn("arrive school", reply)
        self.assertEqual(self.run_ping("arrive", "school"), "sent")
        self.assertEqual(self.bot.sent, ["📍 **School**: Park in lot B"])
        self.assertEqual(self.run_ping("arrive", "SCHOOL", NOW + timedelta(minutes=3)), "repeat")
        self.assertEqual(self.run_ping("leave", "school"), "silent")
        self.cog.set_message("school", "Helmet on", "leave")
        self.assertEqual(self.run_ping("leave", "school", NOW + timedelta(minutes=40)), "sent")
        self.assertEqual(len(self.bot.sent), 2)
        self.assertIn("arrive: Park in lot B", self.cog.listing())

    def test_unknown_place(self) -> None:
        self.assertEqual(self.run_ping("arrive", "gym"), "unknown")
        self.assertIn("gym", self.bot.sent[0])
        self.assertEqual(self.run_ping("leave", "gym"), "silent")

    def test_held_then_flushed(self) -> None:
        self.cog.set_message("home", "Plug in your phone")
        self.assertEqual(self.run_ping("arrive", "home", held=True), "held")
        self.assertEqual(self.bot.sent, [])

        async def not_holding() -> bool:
            return False

        with mock.patch.object(self.cog, "_holding", not_holding):
            asyncio.run(self.cog.flusher.coro(self.cog))
        self.assertEqual(self.bot.sent, ["📍 **home**: Plug in your phone"])

    def test_remove(self) -> None:
        self.cog.set_message("home", "hi")
        self.assertIn("Removed", self.cog.remove("Home"))
        self.assertIn("don't have", self.cog.remove("home"))


if __name__ == "__main__":
    unittest.main()
