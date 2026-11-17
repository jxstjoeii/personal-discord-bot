from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks

from assistant.addons.base import Addon
from assistant.health_core import log_problems, report, run_checks
from assistant.tools import AssistantTool

log = logging.getLogger(__name__)

LOG_FILE = Path(os.getenv("LOCALAPPDATA", "")) / "PatriciaBot" / "bot.log"
WEEKDAY = 6        # Sunday
HOUR = 18          # 6 PM


class Health(Addon):
    addon_name = "health"
    addon_description = "A weekly read-only PC check-up: disk space, updates, Tailscale, and my start-up task."

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._busy = asyncio.Lock()

    async def cog_load(self) -> None:
        self.weekly.start()

    async def cog_unload(self) -> None:
        self.weekly.cancel()

    def build(self) -> str:
        data = run_checks()
        return report(data, log_problems(LOG_FILE, datetime.now()))

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="pc_health_check",
                description=(
                    "Run the read-only PC check-up: disk space, Windows updates, uptime, Tailscale, "
                    "and Patricia's start-up task. Takes up to a minute."
                ),
                parameters={"type": "object", "properties": {}},
                handler=lambda ctx: self.build(),
            )
        ]

    @tasks.loop(minutes=5)
    async def weekly(self) -> None:
        settings = self.bot.settings
        now = datetime.now(settings.timezone)
        if now.weekday() != WEEKDAY or now.hour < HOUR or self._busy.locked():
            return
        week = now.strftime("%G-W%V")
        async with self._busy:
            if not self.bot.db.mark_daily("health", week):
                return
            try:
                text = await asyncio.to_thread(self.build)
                owner = self.bot.get_user(settings.owner_id) or await self.bot.fetch_user(settings.owner_id)
                await owner.send(text)
                log.info("Weekly PC check-up sent")
            except Exception:
                log.exception("Weekly PC check-up failed")

    @weekly.before_loop
    async def before_weekly(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="pchealth", description="Run the PC check-up now")
    async def pchealth_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        text = await asyncio.to_thread(self.build)
        await interaction.followup.send(text)


async def setup(bot) -> None:
    await bot.add_cog(Health(bot))
