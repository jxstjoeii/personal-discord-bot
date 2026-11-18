from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import tasks

from assistant import memory
from assistant.addons.base import Addon
from assistant.house import calendar_report, weather_report
from assistant.recap_core import day_facts, week_facts, write

log = logging.getLogger(__name__)

NIGHT_FALLBACK_HOUR = 23     # If he hasn't said good night by 11 PM, the recap comes anyway.
WEEKLY_DAY = 6               # Sunday
WEEKLY_HOUR = 19             # 7 PM


class Recap(Addon):
    addon_name = "recap"
    addon_description = "A nightly recap when you go to bed, and a weekly look back on Sundays."

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._busy = asyncio.Lock()

    async def cog_load(self) -> None:
        self.clock.start()

    async def cog_unload(self) -> None:
        self.clock.cancel()

    def _night_key(self, now: datetime) -> str:
        # After midnight still counts as the evening before.
        return (now.date() - timedelta(days=1) if now.hour < 5 else now.date()).isoformat()

    def build(self, kind: str) -> str:
        settings = self.bot.settings
        tz = settings.timezone
        now = datetime.now(tz)
        owner = settings.owner_id
        if kind == "week":
            facts = week_facts(self.bot.db, owner, tz, now)
        else:
            extras = {}
            try:
                extras["weather_tomorrow"] = weather_report(tz, now, "tomorrow")
            except Exception as exc:
                extras["weather_tomorrow"] = f"unavailable ({exc})"
            try:
                extras["calendar_tomorrow"] = calendar_report(tz, now, "tomorrow")
            except Exception as exc:
                extras["calendar_tomorrow"] = f"unavailable ({exc})"
            facts = day_facts(self.bot.db, owner, tz, now, extras)
        return write(settings, kind, facts, memory.prompt_block())

    async def send(self, kind: str) -> None:
        settings = self.bot.settings
        text = await asyncio.to_thread(self.build, kind)
        owner = self.bot.get_user(settings.owner_id) or await self.bot.fetch_user(settings.owner_id)
        await owner.send(text)
        self.bot.db.add_message(settings.owner_id, "assistant", f"[{'Weekly' if kind == 'week' else 'Nightly'} recap: {text[:600]}]")

    async def nightly_now(self) -> None:
        """Sends tonight's recap once, for example when Joeii says he's going to bed."""
        if not self.bot.settings.recap_enabled:
            return
        now = datetime.now(self.bot.settings.timezone)
        if not self.bot.db.mark_daily("recap", self._night_key(now)):
            return
        try:
            await self.send("day")
        except Exception:
            log.exception("Nightly recap failed")

    def nightly_soon(self) -> None:
        """Safe to call from any thread."""
        asyncio.run_coroutine_threadsafe(self.nightly_now(), self.bot.loop)

    @tasks.loop(minutes=5)
    async def clock(self) -> None:
        settings = self.bot.settings
        if not settings.recap_enabled or self._busy.locked():
            return
        now = datetime.now(settings.timezone)
        async with self._busy:
            if now.hour >= NIGHT_FALLBACK_HOUR:
                await self.nightly_now()
            if now.weekday() == WEEKLY_DAY and now.hour >= WEEKLY_HOUR:
                if self.bot.db.mark_daily("weekly", now.strftime("%G-W%V")):
                    try:
                        await self.send("week")
                    except Exception:
                        log.exception("Weekly recap failed")

    @clock.before_loop
    async def before_clock(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="recap", description="See today's recap or this week's look back")
    @app_commands.choices(which=[
        app_commands.Choice(name="today", value="day"),
        app_commands.Choice(name="this week", value="week"),
    ])
    async def recap_command(self, interaction: discord.Interaction, which: app_commands.Choice[str]) -> None:
        await interaction.response.defer(thinking=True)
        text = await asyncio.to_thread(self.build, which.value)
        await interaction.followup.send(text)


async def setup(bot) -> None:
    await bot.add_cog(Recap(bot))
