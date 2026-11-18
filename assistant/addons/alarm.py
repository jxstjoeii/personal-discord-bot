"""Alarms that "call" Joeii: repeating DMs with Stop/Snooze, plus a beep on the PC speakers."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import tasks

from assistant.addons.base import Addon
from assistant.alarm_core import (
    RING_EVERY,
    SNOOZE,
    alarm_rollover,
    gave_up,
    gave_up_text,
    ring_text,
    should_ring,
    start_beeping,
    stop_beeping,
)
from assistant.channel_log import format_log, write_log
from assistant.formatting import format_stored, format_when
from assistant.timeparse import PastTime, parse_when
from assistant.tools import AssistantTool, ToolContext

log = logging.getLogger(__name__)

WHEN_HELP = "Examples: 7am, tomorrow at 6:30am, in 20 minutes, now."


class AlarmButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"alarm:(?P<action>stop|snooze):(?P<alarm_id>\d+)",
):
    def __init__(self, action: str, alarm_id: int):
        super().__init__(
            discord.ui.Button(
                label="Stop" if action == "stop" else "Snooze 5 min",
                emoji="🛑" if action == "stop" else "😴",
                style=discord.ButtonStyle.danger if action == "stop" else discord.ButtonStyle.secondary,
                custom_id=f"alarm:{action}:{alarm_id}",
            )
        )
        self.action = action
        self.alarm_id = alarm_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str]):
        return cls(match["action"], int(match["alarm_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != interaction.client.settings.owner_id:
            await interaction.response.send_message("This assistant is private.", ephemeral=True)
            return
        cog = interaction.client.get_cog("Alarms")
        if cog is None:
            await interaction.response.send_message("Alarms are not loaded.", ephemeral=True)
            return
        if self.action == "stop":
            text = cog.stop(self.alarm_id)
        else:
            text = cog.snooze(self.alarm_id)
        await interaction.response.edit_message(view=None)
        await interaction.followup.send(text)
        await cog.tidy()


def alarm_view(alarm_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(AlarmButton("stop", alarm_id))
    view.add_item(AlarmButton("snooze", alarm_id))
    return view


class Alarms(Addon):
    addon_name = "alarms"
    addon_description = "Alarms that keep DMing you and beep on the PC until you tap Stop."

    alarm = app_commands.Group(name="alarm", description="Alarms that ring until you stop them")

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._busy = asyncio.Lock()
        self._beeping = False
        self._last_message: dict[int, discord.Message] = {}

    @property
    def _sound(self):
        return self.bot.settings.database_path.parent / "alarm.wav"

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(AlarmButton)
        self.ticker.start()

    async def cog_unload(self) -> None:
        self.ticker.cancel()
        self.bot.remove_dynamic_items(AlarmButton)
        if self._beeping:
            stop_beeping()
            self._beeping = False

    # ------------------------------------------------------------ ringing --

    @tasks.loop(seconds=3)
    async def ticker(self) -> None:
        async with self._busy:
            try:
                await self._tick()
            except Exception:
                log.exception("Alarm check failed")

    @ticker.before_loop
    async def before_ticker(self) -> None:
        await self.bot.wait_until_ready()

    async def _tick(self) -> None:
        # Alarms ring even during class quiet hours: Joeii set the time himself.
        now = datetime.now(timezone.utc)
        db = self.bot.db
        for row in db.alarms_to_start(now):
            db.ring_alarm(row["id"], 0, now)
            log.info("Alarm %s went off", row["id"])
        for row in db.ringing_alarms():
            if not should_ring(row, now):
                continue
            if gave_up(row):
                db.end_alarm(row["id"])
                await self._clear_buttons(row["id"])
                await self._dm(gave_up_text(row))
                continue
            message = await self._dm(ring_text(row), alarm_view(row["id"]))
            await self._clear_buttons(row["id"])
            if message is not None:
                self._last_message[row["id"]] = message
            db.ring_alarm(row["id"], int(row["rings"] or 0) + 1, now + RING_EVERY)
            if int(row["rings"] or 0) == 0:
                self.bot.db.add_message(
                    self.bot.settings.owner_id,
                    "assistant",
                    f"[Alarm #{row['id']} is ringing: {row['label'] or 'Alarm'}. "
                    "If Joeii says stop, I'm up, or similar, use stop_alarm.]",
                )
                await write_log(
                    self.bot,
                    format_log(self.bot.settings.timezone, "Alarm ringing", reply=f"#{row['id']} {row['label']}"),
                )
        await self.tidy()

    async def tidy(self) -> None:
        """Beep while any alarm is ringing, and go quiet once none are."""
        ringing = bool(self.bot.db.ringing_alarms())
        if ringing and not self._beeping:
            self._beeping = await asyncio.to_thread(start_beeping, self._sound)
        elif not ringing and self._beeping:
            await asyncio.to_thread(stop_beeping)
            self._beeping = False
        if not ringing:
            for alarm_id in list(self._last_message):
                await self._clear_buttons(alarm_id)

    async def _dm(self, text: str, view: discord.ui.View | None = None) -> discord.Message | None:
        try:
            user = self.bot.get_user(self.bot.settings.owner_id)
            if user is None:
                user = await self.bot.fetch_user(self.bot.settings.owner_id)
            if view is None:
                return await user.send(text)
            return await user.send(text, view=view)
        except discord.HTTPException:
            log.warning("Could not send an alarm DM")
            return None

    async def _clear_buttons(self, alarm_id: int) -> None:
        message = self._last_message.pop(alarm_id, None)
        if message is None:
            return
        try:
            await message.edit(view=None)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------ actions --

    def stop(self, alarm_id: int | None = None) -> str:
        if alarm_id is None:
            rows = self.bot.db.ringing_alarms()
            if not rows:
                return "No alarm is ringing right now."
            for row in rows:
                self.bot.db.end_alarm(row["id"])
            return "🛑 Alarm off. Good morning!" if len(rows) == 1 else f"🛑 Stopped {len(rows)} alarms."
        row = self.bot.db.get_alarm(alarm_id)
        if row is None or row["state"] == "done":
            return "That alarm is already off."
        self.bot.db.end_alarm(alarm_id)
        return "🛑 Alarm off. Good morning!"

    def snooze(self, alarm_id: int) -> str:
        until = datetime.now(timezone.utc) + SNOOZE
        row = self.bot.db.snooze_alarm(alarm_id, until)
        if row is None:
            return "That alarm is already off."
        minutes = int(SNOOZE.total_seconds() // 60)
        return f"😴 Snoozed. I'll ring again in {minutes} minutes."

    def create(self, user_id: int, when: str, label: str = "") -> str:
        tz = self.bot.settings.timezone
        label = (label or "").strip()[:100]
        text = (when or "").strip().lower()
        if text in {"now", "right now"}:
            due = datetime.now(timezone.utc)
        else:
            try:
                due = parse_when(when, tz)
            except PastTime as exc:
                # "7am" said after 7am means tomorrow morning.
                due = alarm_rollover(exc.when, datetime.now(timezone.utc))
                if due is None:
                    return f"That time already passed ({format_when(exc.when, tz)}). Try 'tomorrow at 7am'."
            except ValueError:
                return "I couldn't read that time. Try '7am', 'tomorrow at 6:30am', or 'in 20 minutes'."
        row = self.bot.db.add_alarm(user_id, label, due)
        name = f": {row['label']}" if row["label"] else ""
        return (
            f"⏰ Alarm #{row['id']} set for {format_stored(row['due_at'], tz)}{name}. "
            "I'll keep DMing you and beep on your PC until you tap Stop."
        )

    def listing(self, user_id: int) -> str:
        rows = self.bot.db.open_alarms(user_id)
        if not rows:
            return "No alarms set."
        tz = self.bot.settings.timezone
        lines = []
        for row in rows[:15]:
            status = " (ringing now)" if row["state"] == "ringing" else ""
            name = f" — {row['label']}" if row["label"] else ""
            lines.append(f"#{row['id']} {format_stored(row['due_at'], tz)}{name}{status}")
        return "\n".join(lines)

    def cancel(self, user_id: int, alarm_id: int) -> str:
        row = self.bot.db.get_alarm(int(alarm_id))
        if row is None or row["user_id"] != user_id or row["state"] == "done":
            return f"There is no alarm #{alarm_id} set."
        self.bot.db.end_alarm(row["id"])
        return f"Cancelled alarm #{row['id']}."

    # ------------------------------------------------------------ tools --

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="set_alarm",
                description=(
                    "Set an alarm that 'calls' Joeii: when it goes off, Patricia DMs him every 30 "
                    "seconds with Stop and Snooze buttons and beeps on his PC speakers until he "
                    "stops it. Use when he asks for an alarm, to be woken up, or to be called at a "
                    "time. For a plain one-time nudge, use create_reminder instead."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "when": {"type": "string", "description": "When it goes off. " + WHEN_HELP},
                        "label": {"type": "string", "description": "Optional. What it's for, like 'wake up'."},
                    },
                    "required": ["when"],
                },
                handler=lambda ctx, when, label="": self.create(ctx.user_id, when, label),
            ),
            AssistantTool(
                name="list_alarms",
                description="List Joeii's alarms that are set or ringing.",
                parameters={"type": "object", "properties": {}},
                handler=lambda ctx: self.listing(ctx.user_id),
            ),
            AssistantTool(
                name="stop_alarm",
                description=(
                    "Stop every alarm that is ringing right now. Use when Joeii says stop, I'm up, "
                    "I'm awake, or similar while an alarm is ringing."
                ),
                parameters={"type": "object", "properties": {}},
                handler=lambda ctx: self.stop(),
            ),
            AssistantTool(
                name="cancel_alarm",
                description="Cancel an alarm that hasn't gone off yet, by its id from list_alarms.",
                parameters={
                    "type": "object",
                    "properties": {"alarm_id": {"type": "integer", "description": "The alarm id."}},
                    "required": ["alarm_id"],
                },
                handler=lambda ctx, alarm_id: self.cancel(ctx.user_id, alarm_id),
            ),
        ]

    # ------------------------------------------------------------ commands --

    @alarm.command(name="set", description="Set an alarm that rings until you tap Stop")
    @app_commands.describe(when=WHEN_HELP, label="Optional. What it's for, like wake up")
    async def set_cmd(self, interaction: discord.Interaction, when: str, label: str | None = None) -> None:
        await interaction.response.send_message(self.create(interaction.user.id, when, label or ""))

    @alarm.command(name="list", description="Show your alarms")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(self.listing(interaction.user.id))

    @alarm.command(name="stop", description="Stop a ringing alarm")
    async def stop_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(self.stop())
        await self.tidy()

    @alarm.command(name="cancel", description="Cancel an alarm by its id")
    @app_commands.describe(alarm_id="The id shown by /alarm list")
    async def cancel_cmd(self, interaction: discord.Interaction, alarm_id: int) -> None:
        await interaction.response.send_message(self.cancel(interaction.user.id, alarm_id))
        await self.tidy()


async def setup(bot) -> None:
    await bot.add_cog(Alarms(bot))
