from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks
from discord import app_commands

from assistant import memory
from assistant.addons.base import Addon
from assistant.formatting import format_stored
from assistant.house import calendar_report, load_briefing, weather_report
from assistant.life_core import birthday_line, upcoming_birthdays
from assistant.morning_core import hero_of_the_day, riding_rules, write_hello

log = logging.getLogger(__name__)

LATEST_HOUR = 12  # If she comes online after noon, today's hello is skipped.


class Morning(Addon):
    addon_name = "morning"
    addon_description = "A morning hello in Discord with weather, a riding verdict, what's due, and something fun."

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._busy = asyncio.Lock()

    async def cog_load(self) -> None:
        self.sender.start()

    async def cog_unload(self) -> None:
        self.sender.cancel()

    def gather(self, now: datetime) -> dict:
        """Runs in a worker thread: everything the hello talks about."""
        settings = self.bot.settings
        tz = settings.timezone
        owner = settings.owner_id
        try:
            weather = weather_report(tz, now, "today")
        except Exception as exc:
            weather = f"Weather unavailable: {exc}"
        try:
            calendar = calendar_report(tz, now, "today")
        except Exception as exc:
            calendar = f"Calendar unavailable: {exc}"
        try:
            _root, config = load_briefing()
        except Exception:
            config = None
        end_of_day = datetime.combine(now.date(), datetime.max.time(), tzinfo=tz).astimezone(timezone.utc)
        reminders = []
        for row in self.bot.db.list_reminders(owner):
            if datetime.fromisoformat(row["due_at"]) <= end_of_day:
                reminders.append(f"- {format_stored(row['due_at'], tz)}: {row['text']}")
        soon = datetime.now(timezone.utc) + timedelta(days=3)
        due = []
        for row in self.bot.db.list_assignments(owner):
            if datetime.fromisoformat(row["due_at"]) <= soon:
                course = f" ({row['course']})" if row.get("course") else ""
                due.append(f"- {row['title']}{course}: due {format_stored(row['due_at'], tz)}")
        hero, role = hero_of_the_day(now.date())
        return {
            "weather": weather,
            "calendar": calendar,
            "riding": riding_rules(config),
            "reminders": "\n".join(reminders),
            "due": "\n".join(due),
            "birthdays": "\n".join(
                birthday_line(r, now.date()) for r in upcoming_birthdays(self.bot.db.list_birthdays(), now.date(), 3)
            ),
            "hero": hero,
            "role": role,
        }

    def compose(self, now: datetime) -> str:
        facts = self.gather(now)
        return write_hello(self.bot.settings, facts, memory.prompt_block(), now)

    async def send_hello(self, now: datetime) -> None:
        settings = self.bot.settings
        text = await asyncio.to_thread(self.compose, now)
        owner = self.bot.get_user(settings.owner_id) or await self.bot.fetch_user(settings.owner_id)
        await owner.send(text)
        self.bot.db.add_message(settings.owner_id, "assistant", f"[Morning hello: {text[:600]}]")

    @tasks.loop(seconds=60)
    async def sender(self) -> None:
        settings = self.bot.settings
        if not settings.morning_enabled or self._busy.locked():
            return
        now = datetime.now(settings.timezone)
        start = datetime.combine(now.date(), settings.morning_time, tzinfo=settings.timezone)
        if not start <= now < now.replace(hour=LATEST_HOUR, minute=0, second=0, microsecond=0):
            return
        async with self._busy:
            if not self.bot.db.mark_daily("morning", now.date().isoformat()):
                return
            try:
                await self.send_hello(now)
                log.info("Morning hello sent")
            except Exception:
                log.exception("Morning hello failed")

    @sender.before_loop
    async def before_sender(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="morning", description="Get the morning hello right now")
    async def morning_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        now = datetime.now(self.bot.settings.timezone)
        text = await asyncio.to_thread(self.compose, now)
        await interaction.followup.send(text)


async def setup(bot) -> None:
    await bot.add_cog(Morning(bot))
