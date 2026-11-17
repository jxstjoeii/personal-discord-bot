from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

import discord
from discord.ext import tasks

from assistant import pc
from assistant.addons.base import Addon
from assistant.bedtime_core import current_slot, night_window
from assistant.status_core import next_line, pick_mood

log = logging.getLogger(__name__)

ROTATE_SECONDS = 15 * 60


class Status(Addon):
    addon_name = "status"
    addon_description = "Changes Patricia's Discord status to fit the time and what you're doing."

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._mood: str | None = None
        self._line: str | None = None
        self._changed_at = 0.0

    async def cog_load(self) -> None:
        self.updater.start()

    async def cog_unload(self) -> None:
        self.updater.cancel()

    async def _current_mood(self) -> str:
        settings = self.bot.settings
        now = datetime.now(settings.timezone)
        in_bedtime = bedtime_done = False
        if settings.bedtime_enabled:
            night, start_at, end_at = night_window(now, settings.bedtime_start, settings.bedtime_end)
            if current_slot(now, start_at, end_at, settings.bedtime_every) is not None:
                row = self.bot.db.get_bedtime(night.isoformat()) or {}
                bedtime_done = bool(row.get("done_at"))
                in_bedtime = not bedtime_done
        gaming = False
        if not in_bedtime and not bedtime_done:
            gaming = await asyncio.to_thread(pc.running_game, settings) is not None
        return pick_mood(now, in_bedtime=in_bedtime, bedtime_done=bedtime_done, gaming=gaming)

    @tasks.loop(seconds=60)
    async def updater(self) -> None:
        try:
            mood = await self._current_mood()
        except Exception:
            log.exception("Working out the status failed")
            return
        stale = time.monotonic() - self._changed_at >= ROTATE_SECONDS
        if mood == self._mood and not stale:
            return
        line = next_line(mood, self._line if mood == self._mood else None)
        try:
            await self.bot.change_presence(activity=discord.CustomActivity(name=line))
        except discord.HTTPException:
            log.warning("Could not change the status")
            return
        self._mood, self._line, self._changed_at = mood, line, time.monotonic()

    @updater.before_loop
    async def before_updater(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot) -> None:
    await bot.add_cog(Status(bot))
