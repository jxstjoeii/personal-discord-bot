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

from assistant.app import AssistantBot
from assistant.brain import system_prompt
from assistant.config import ConfigError, Settings, load_settings
from assistant.db import Database
from assistant.formatting import (
    normalize_tags,
    note_summary,
    page_slice,
    split_discord,
)
from assistant.loader import describe_addons, load_builtin, load_user_addons, unload_user_addons
from assistant.timeparse import PastTime, parse_when
from assistant.tools import AssistantTool, ToolContext, invoke_tool

PACIFIC = ZoneInfo("America/Los_Angeles")


def make_settings(folder: Path) -> Settings:
    return Settings(
        discord_token="test-token",
        owner_id=42,
        guild_id=None,
        xai_api_key="",
        model="grok-4.7",
        reasoning_effort="low",
        timezone=PACIFIC,
        database_path=folder / "assistant.db",
        user_addons_path=folder / "user_addons",
        phone_token="",
        phone_port=8787,
        log_channel_id=None,
    )


class FormattingTests(unittest.TestCase):
    def test_tags_and_pages(self) -> None:
        self.assertEqual(normalize_tags(" School, math, School "), "school, math")
        chunk, page, total = page_slice(list(range(8)), 2, page_size=6)
        self.assertEqual(chunk, [6, 7])
        self.assertEqual((page, total), (2, 2))
        summary = note_summary({"id": 3, "title": "Grocery", "body": "milk\neggs", "tags": "home"})
        self.assertIn("#3 Grocery", summary)
        self.assertIn("milk eggs", summary)

    def test_split_discord(self) -> None:
        self.assertEqual(split_discord("  hello  "), ["hello"])
        parts = split_discord("word " * 800, limit=100)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 100 for part in parts))


class TimeTests(unittest.TestCase):
    def test_relative_and_explicit_times(self) -> None:
        now = datetime(2026, 11, 3, 12, 0, tzinfo=PACIFIC)
        due = parse_when("in 2 hours", PACIFIC, now=now)
        self.assertEqual(due, datetime(2026, 11, 3, 22, 0, tzinfo=timezone.utc))
        later = parse_when("November 5 2026 3:00 pm", PACIFIC, now=now)
        self.assertEqual(later, datetime(2026, 11, 5, 23, 0, tzinfo=timezone.utc))

    def test_past_and_garbage(self) -> None:
        now = datetime(2026, 11, 3, 12, 0, tzinfo=PACIFIC)
        with self.assertRaises(PastTime):
            parse_when("November 1 2026 3:00 pm", PACIFIC, now=now)
        with self.assertRaises(ValueError):
            parse_when("not a real time blah", PACIFIC, now=now)


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.db")

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_reminders(self) -> None:
        now = datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc)
        future = self.db.add_reminder(7, "stretch", now + timedelta(hours=2))
        past = self.db.add_reminder(7, "water", now - timedelta(minutes=5))
        self.assertEqual([row["id"] for row in self.db.due_reminders(now)], [past["id"]])
        self.assertEqual(len(self.db.list_reminders(7)), 2)
        self.assertEqual(self.db.bump_reminder_attempt(past["id"]), 1)
        self.db.mark_reminder_sent(past["id"])
        self.assertEqual([row["id"] for row in self.db.due_reminders(now)], [])
        cancelled = self.db.cancel_reminder(7, future["id"])
        self.assertEqual(cancelled["text"], "stretch")
        self.assertIsNone(self.db.cancel_reminder(7, future["id"]))

    def test_notes_and_messages(self) -> None:
        first = self.db.add_note(7, "Grocery", "oat milk", "Home, Errands")
        second = self.db.add_note(7, "Homework", "finish chapter 7", "school")
        self.assertEqual(first["tags"], "home, errands")
        found = self.db.search_notes(7, tag="meal prep")
        self.assertEqual(found, [])
        meal = self.db.add_note(7, "Lunch", "soup", "Meal Prep")
        self.assertEqual(self.db.search_notes(7, tag="meal prep")[0]["id"], meal["id"])
        self.assertEqual(self.db.search_notes(7, query="%"), [])
        self.assertEqual(self.db.search_notes(7, query="chapter")[0]["id"], second["id"])
        updated = self.db.update_note(7, first["id"], title="Store")
        self.assertEqual(updated["title"], "Store")
        self.assertEqual(updated["body"], "oat milk")
        self.assertIsNotNone(self.db.delete_note(7, second["id"]))
        self.assertIsNone(self.db.get_note(7, second["id"]))

        self.db.add_message(7, "user", "one", keep=2)
        self.db.add_message(7, "assistant", "two", keep=2)
        self.db.add_message(7, "user", "three", keep=2)
        recent = self.db.recent_messages(7)
        self.assertEqual([row["content"] for row in recent], ["two", "three"])
        self.db.clear_messages(7)
        self.assertEqual(self.db.recent_messages(7), [])


class ToolTests(unittest.TestCase):
    def test_invoke_and_prompt(self) -> None:
        def handler(ctx: ToolContext, name: str) -> str:
            return f"{name}:{ctx.user_id}"

        tool = AssistantTool(
            name="greet",
            description="Say hello",
            parameters={"type": "object", "properties": {}},
            handler=handler,
        )
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        ctx = ToolContext(5, make_settings(Path(folder.name)), Database(Path(folder.name) / "x.db"))
        self.addCleanup(ctx.db.close)
        self.assertEqual(
            invoke_tool({"greet": tool}, ctx, "greet", '{"name": "Ada", "extra": 1}'),
            "Ada:5",
        )
        self.assertIn("Unknown tool", invoke_tool({}, ctx, "missing", "{}"))
        prompt = system_prompt(ctx.settings, ["greet"])
        self.assertIn("greet", prompt)
        self.assertIn("America/Los_Angeles", prompt)


class ConfigTests(unittest.TestCase):
    def test_load_settings(self) -> None:
        with mock.patch("assistant.config.load_dotenv"), mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ConfigError):
                load_settings()
        env = {
            "DISCORD_TOKEN": "token",
            "DISCORD_OWNER_ID": "99",
            "DISCORD_GUILD_ID": "123",
            "XAI_API_KEY": "key",
            "XAI_MODEL": "grok-4.7",
            "XAI_REASONING": "low",
            "TIMEZONE": "America/Los_Angeles",
        }
        with mock.patch("assistant.config.load_dotenv"), mock.patch.dict("os.environ", env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.owner_id, 99)
        self.assertEqual(settings.guild_id, 123)
        self.assertEqual(settings.phone_token, "")
        self.assertEqual(settings.phone_port, 8787)
        self.assertIsNone(settings.log_channel_id)
        with mock.patch("assistant.config.load_dotenv"), mock.patch.dict(
            "os.environ", {**env, "TIMEZONE": "Not/AZone"}, clear=True
        ):
            with self.assertRaises(ConfigError):
                load_settings()
        with mock.patch("assistant.config.load_dotenv"), mock.patch.dict(
            "os.environ", {**env, "DISCORD_OWNER_ID": "abc"}, clear=True
        ):
            with self.assertRaises(ConfigError):
                load_settings()


class LoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_addons_skip_private_files(self) -> None:
        class FakeBot:
            def __init__(self) -> None:
                self.cogs: dict = {}

            async def add_cog(self, cog, *, override: bool = False) -> None:
                self.cogs[type(cog).__name__] = cog

            async def remove_cog(self, name: str) -> None:
                self.cogs.pop(name, None)

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "_secret.py").write_text("raise RuntimeError('should not load')\n", encoding="utf-8")
            (folder / "broken.py").write_text("VALUE = 1\n", encoding="utf-8")
            (folder / "sample.py").write_text(
                "class Sample:\n"
                "    addon_name = 'sample'\n"
                "    addon_description = 'A sample.'\n"
                "    def assistant_tools(self):\n"
                "        return []\n"
                "async def setup(bot):\n"
                "    await bot.add_cog(Sample())\n",
                encoding="utf-8",
            )
            bot = FakeBot()
            loaded, errors = await load_user_addons(bot, folder)
            self.assertEqual(loaded, ["sample"])
            self.assertEqual(len(errors), 1)
            self.assertIn("broken.py", errors[0])
            self.assertIn("sample", describe_addons(bot))
            await unload_user_addons(bot)
            self.assertEqual(bot.cogs, {})


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        folder = Path(self.tmp.name)
        self.bot = AssistantBot(make_settings(folder), Database(folder / "assistant.db"))

        async def ready() -> None:
            return None

        self.bot.wait_until_ready = ready
        await load_builtin(self.bot)

    async def asyncTearDown(self) -> None:
        reminders = self.bot.get_cog("Reminders")
        if reminders is not None:
            reminders.delivery.cancel()
        await self.bot.close()
        self.tmp.cleanup()

    async def test_builtin_commands_register(self) -> None:
        names = sorted(command.name for command in self.bot.tree.get_commands())
        self.assertEqual(
            names,
            ["addons", "ask", "catalog", "clear_chat", "help", "note", "reload_addons", "remind"],
        )
        remind = next(command for command in self.bot.tree.get_commands() if command.name == "remind")
        note = next(command for command in self.bot.tree.get_commands() if command.name == "note")
        self.assertEqual(sorted(item.name for item in remind.commands), ["add", "cancel", "list"])
        self.assertEqual(sorted(item.name for item in note.commands), ["add", "delete", "edit", "show"])


class ChannelLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_format_and_skip_without_channel(self) -> None:
        from assistant.channel_log import format_log, write_log

        moment = datetime(2026, 11, 4, 9, 5, tzinfo=PACIFIC)
        text = format_log(PACIFIC, "Phone", "hello", "hi there", now=moment)
        self.assertIn("Phone · Nov 04, 09:05 AM", text)
        self.assertIn("You: hello", text)
        self.assertIn("Patricia: hi there", text)

        class FakeBot:
            def __init__(self) -> None:
                self.settings = make_settings(Path("."))
                self.ready = False

            def is_ready(self) -> bool:
                self.ready = True
                return False

            async def wait_until_ready(self) -> None:
                raise AssertionError("should not wait without a log channel")

        await write_log(FakeBot(), "hello")


class PhoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_phone_key_and_message(self) -> None:
        from assistant.phone import authorized, message

        self.assertFalse(authorized(None, "secret"))
        self.assertFalse(authorized("secret", "secret"))
        self.assertFalse(authorized("Bearer nope", "secret"))
        self.assertTrue(authorized("Bearer secret", "secret"))

        class FakeAsk:
            async def reply_for_user(self, user_id: int, text: str, **kwargs) -> str:
                return f"{user_id}:{text}"

        class FakeBot:
            def __init__(self) -> None:
                self.settings = make_settings(Path("."))
                self.settings = type(self.settings)(
                    **{
                        **self.settings.__dict__,
                        "phone_token": "secret",
                    }
                )

            def get_cog(self, name: str):
                self.cog_name = name
                return FakeAsk()

        class FakeRequest:
            def __init__(self, header: str, text: str) -> None:
                self.headers = {
                    "Authorization": header,
                    "Content-Type": "application/json",
                }
                self.method = "POST"
                self.query: dict = {}
                self.app = {"bot": FakeBot()}
                self._text = text

            async def json(self) -> dict:
                return {"text": self._text}

        denied = await message(FakeRequest("Bearer nope", "hello"))
        self.assertEqual(denied.status, 401)
        accepted = await message(FakeRequest("Bearer secret", "hello"))
        self.assertEqual(accepted.status, 200)
        self.assertIn(b'"reply": "42:hello"', accepted.body)


if __name__ == "__main__":
    unittest.main()
