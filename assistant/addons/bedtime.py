from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import tasks

from assistant.addons.base import Addon
from assistant.bedtime_core import clock_text, current_slot, night_window, write_nudge
from assistant.channel_log import format_log, write_log
from assistant.tools import AssistantTool, ToolContext

log = logging.getLogger(__name__)

GOOD_NIGHT = "Good night, Joeii. Thank you for listening to me. Sleep well. 🌙"


class BedButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"bed:done:(?P<night>\d{4}-\d{2}-\d{2})",
):
    def __init__(self, night: str):
        super().__init__(
            discord.ui.Button(
                label="I'm going to bed",
                emoji="😴",
                style=discord.ButtonStyle.primary,
                custom_id=f"bed:done:{night}",
            )
        )
        self.night = night

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str]):
        return cls(match["night"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != interaction.client.settings.owner_id:
            await interaction.response.send_message("This assistant is private.", ephemeral=True)
            return
        cog = interaction.client.get_cog("Bedtime")
        if cog is not None:
            cog.finish_night(self.night, "button")
        await interaction.response.edit_message(view=None)
        await interaction.followup.send(GOOD_NIGHT)


def bed_view(night: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(BedButton(night))
    return view


class Bedtime(Addon):
    addon_name = "bedtime"
    addon_description = "Nudges you to get ready for bed every half hour from 8:30 PM until you go."

    bedtime = app_commands.Group(name="bedtime", description="Bedtime nudges")

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._busy = asyncio.Lock()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(BedButton)
        self.nudger.start()

    async def cog_unload(self) -> None:
        self.nudger.cancel()
        self.bot.remove_dynamic_items(BedButton)

    # ------------------------------------------------------------ state --

    def _window(self, now: datetime | None = None):
        settings = self.bot.settings
        now = now or datetime.now(settings.timezone)
        night, start_at, end_at = night_window(now, settings.bedtime_start, settings.bedtime_end)
        return now, night.isoformat(), start_at, end_at

    def finish_night(self, night: str, how: str) -> bool:
        """Stop the nudges for this night. False if it was already stopped."""
        row = self.bot.db.get_bedtime(night)
        if row and row.get("done_at"):
            return False
        self.bot.db.finish_bedtime(night)
        log.info("Bedtime finished for %s (%s)", night, how)
        recap = self.bot.get_cog("Recap")
        if recap is not None:
            recap.nightly_soon()
        return True

    # ------------------------------------------------------------ tools --

    def assistant_tools(self) -> list[AssistantTool]:
        if not self.bot.settings.bedtime_enabled:
            return []
        return [
            AssistantTool(
                name="going_to_bed",
                description=(
                    "Stop tonight's bedtime nudges. Use when Joeii says he is going to bed, "
                    "heading to sleep, getting ready for bed now, or otherwise clearly done for "
                    "the night, including in reply to a bedtime nudge. Also use when he asks to "
                    "skip the nudges tonight."
                ),
                parameters={"type": "object", "properties": {}},
                handler=self._tool_done,
            )
        ]

    def _tool_done(self, ctx: ToolContext) -> str:
        _now, night, _start, _end = self._window()
        if self.finish_night(night, "chat"):
            return "Tonight's bedtime nudges are stopped. Wish Joeii a good night, briefly and warmly."
        return "Tonight's bedtime nudges were already stopped."

    # ----------------------------------------------------------- nudger --

    @tasks.loop(seconds=30)
    async def nudger(self) -> None:
        if not self.bot.settings.bedtime_enabled or self._busy.locked():
            return
        async with self._busy:
            try:
                await self._maybe_nudge()
            except Exception:
                log.exception("Bedtime nudge failed")

    @nudger.before_loop
    async def before_nudger(self) -> None:
        await self.bot.wait_until_ready()

    async def _maybe_nudge(self) -> None:
        settings = self.bot.settings
        now, night, start_at, end_at = self._window()
        slot = current_slot(now, start_at, end_at, settings.bedtime_every)
        if slot is None:
            return
        row = self.bot.db.get_bedtime(night) or {}
        if row.get("done_at"):
            return
        if row.get("last_slot") is not None and int(row["last_slot"]) >= slot:
            return
        earlier = json.loads(row.get("messages") or "[]")
        number = len(earlier) + 1
        # Claim the slot first, so a slow reply can't cause a second nudge.
        self.bot.db.save_bedtime(night, slot, earlier)
        text = await asyncio.to_thread(write_nudge, settings, number, now, earlier)
        owner = self.bot.get_user(settings.owner_id) or await self.bot.fetch_user(settings.owner_id)
        await owner.send(text, view=bed_view(night))
        earlier.append(text)
        self.bot.db.save_bedtime(night, slot, earlier)
        self.bot.db.add_message(
            settings.owner_id,
            "assistant",
            f"[Bedtime nudge #{number} at {clock_text(now)}: {text} "
            "It repeats until Joeii says he is going to bed.]",
        )
        await write_log(self.bot, format_log(settings.timezone, f"Bedtime nudge #{number}", reply=text))

    # --------------------------------------------------------- commands --

    @bedtime.command(name="done", description="Tell Patricia you're going to bed, so the nudges stop tonight")
    async def done_command(self, interaction: discord.Interaction) -> None:
        _now, night, _start, _end = self._window()
        self.finish_night(night, "command")
        await interaction.response.send_message(GOOD_NIGHT)

    @bedtime.command(name="status", description="When the bedtime nudges start and whether they're on tonight")
    async def status_command(self, interaction: discord.Interaction) -> None:
        settings = self.bot.settings
        if not settings.bedtime_enabled:
            await interaction.response.send_message("Bedtime nudges are off. Set BEDTIME=on in .env.")
            return
        now, night, start_at, end_at = self._window()
        row = self.bot.db.get_bedtime(night) or {}
        sent = len(json.loads(row.get("messages") or "[]"))
        lines = [
            f"Nudges start at {clock_text(settings.bedtime_start)} and repeat every "
            f"{settings.bedtime_every} minutes until you go to bed, or {clock_text(settings.bedtime_end)}."
        ]
        if row.get("done_at"):
            lines.append("Tonight: done. You told me you're going to bed.")
        elif now < start_at:
            lines.append(f"Tonight: the first one comes at {clock_text(start_at)}.")
        else:
            lines.append(f"Tonight: {sent} sent so far.")
        await interaction.response.send_message("\n".join(lines))


async def setup(bot) -> None:
    await bot.add_cog(Bedtime(bot))
