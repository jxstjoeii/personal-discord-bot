from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import tasks

from assistant.addons.base import Addon
from assistant.house import load_briefing
from assistant.meds_core import due, med_label, nudge_text, streak, taken_text
from assistant.tools import AssistantTool, ToolContext

log = logging.getLogger(__name__)

SNOOZE = timedelta(minutes=30)


class MedsButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"meds:(?P<action>took|snooze):(?P<day>\d{4}-\d{2}-\d{2})",
):
    def __init__(self, action: str, day: str):
        super().__init__(
            discord.ui.Button(
                label="Took them" if action == "took" else "Snooze 30 min",
                emoji="✅" if action == "took" else "⏰",
                style=discord.ButtonStyle.success if action == "took" else discord.ButtonStyle.secondary,
                custom_id=f"meds:{action}:{day}",
            )
        )
        self.action = action
        self.day = day

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str]):
        return cls(match["action"], match["day"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != interaction.client.settings.owner_id:
            await interaction.response.send_message("This assistant is private.", ephemeral=True)
            return
        cog = interaction.client.get_cog("Meds")
        if cog is None:
            await interaction.response.send_message("The medication check-in is not loaded.", ephemeral=True)
            return
        if self.action == "took":
            text = cog.mark_taken(self.day)
            await interaction.response.edit_message(view=None)
            await interaction.followup.send(text)
        else:
            cog.snooze(self.day)
            await interaction.response.edit_message(view=None)
            await interaction.followup.send("⏰ Okay, I'll ask again in 30 minutes.")


def meds_view(day: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(MedsButton("took", day))
    view.add_item(MedsButton("snooze", day))
    return view


class Meds(Addon):
    addon_name = "meds"
    addon_description = "Morning medication check-in with a button, gentle repeats, and a streak."

    meds = app_commands.Group(name="meds", description="Medication check-in")

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._busy = asyncio.Lock()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(MedsButton)
        self.checker.start()

    async def cog_unload(self) -> None:
        self.checker.cancel()
        self.bot.remove_dynamic_items(MedsButton)

    # ------------------------------------------------------------ state --

    def _label(self) -> str:
        try:
            _root, config = load_briefing()
        except Exception:
            config = None
        return med_label(self.bot.settings, config)

    def _today(self) -> tuple[datetime, str]:
        now = datetime.now(self.bot.settings.timezone)
        return now, now.date().isoformat()

    def mark_taken(self, day: str | None = None) -> str:
        now, today = self._today()
        day = day or today
        row = self.bot.db.get_meds(day) or {}
        if not row.get("taken_at"):
            self.bot.db.take_meds(day)
        count = streak(set(self.bot.db.meds_taken_days()), now.date())
        if day != today:
            return "Logged for that day. 💊"
        return taken_text(count)

    def snooze(self, day: str) -> None:
        now = datetime.now(timezone.utc)
        row = self.bot.db.get_meds(day) or {}
        self.bot.db.save_meds(day, int(row.get("nudges") or 0), now + SNOOZE)

    # ------------------------------------------------------------ tools --

    def assistant_tools(self) -> list[AssistantTool]:
        if not self.bot.settings.meds_enabled:
            return []
        return [
            AssistantTool(
                name="took_meds",
                description=(
                    "Log that Joeii took his morning medication today. Use when he says he took his "
                    "meds or pills, including in reply to a medication check-in."
                ),
                parameters={"type": "object", "properties": {}},
                handler=lambda ctx: self.mark_taken(),
            ),
            AssistantTool(
                name="meds_status",
                description="Whether Joeii has taken his medication today, and his current streak.",
                parameters={"type": "object", "properties": {}},
                handler=self._tool_status,
            ),
        ]

    def _tool_status(self, ctx: ToolContext) -> str:
        now, today = self._today()
        row = self.bot.db.get_meds(today) or {}
        count = streak(set(self.bot.db.meds_taken_days()), now.date())
        if row.get("taken_at"):
            return f"Taken today. Streak: {count} day(s)."
        yesterday = streak(set(self.bot.db.meds_taken_days()), now.date() - timedelta(days=1))
        return f"Not logged yet today. Streak before today: {yesterday} day(s)."

    # ---------------------------------------------------------- checker --

    @tasks.loop(seconds=30)
    async def checker(self) -> None:
        if not self.bot.settings.meds_enabled or self._busy.locked():
            return
        async with self._busy:
            try:
                await self._maybe_nudge()
            except Exception:
                log.exception("Medication check-in failed")

    @checker.before_loop
    async def before_checker(self) -> None:
        await self.bot.wait_until_ready()

    async def _maybe_nudge(self) -> None:
        settings = self.bot.settings
        now, today = self._today()
        start = datetime.combine(now.date(), settings.meds_start, tzinfo=settings.timezone)
        until = datetime.combine(now.date(), settings.meds_until, tzinfo=settings.timezone)
        row = self.bot.db.get_meds(today)
        if not due(now, row, start, until):
            return
        number = int((row or {}).get("nudges") or 0) + 1
        following = now + timedelta(minutes=settings.meds_every)
        last = following >= until
        label = await asyncio.to_thread(self._label)
        self.bot.db.save_meds(today, number, following)
        owner = self.bot.get_user(settings.owner_id) or await self.bot.fetch_user(settings.owner_id)
        text = nudge_text(number, label, last)
        await owner.send(text, view=meds_view(today))
        self.bot.db.add_message(settings.owner_id, "assistant", f"[Medication check-in #{number}: {text}]")
        log.info("Medication check-in %s sent", number)

    # --------------------------------------------------------- commands --

    @meds.command(name="took", description="Log that you took your medication today")
    async def took_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(self.mark_taken())

    @meds.command(name="status", description="Whether you've taken your medication today, and your streak")
    async def status_command(self, interaction: discord.Interaction) -> None:
        settings = self.bot.settings
        text = self._tool_status(ToolContext(interaction.user.id, settings, self.bot.db))
        hour = settings.meds_start.strftime("%I:%M %p").lstrip("0")
        await interaction.response.send_message(f"{text}\nCheck-ins start at {hour}.")


async def setup(bot) -> None:
    await bot.add_cog(Meds(bot))
