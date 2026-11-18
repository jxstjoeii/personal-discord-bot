"""Mood check-ins and birthday reminders."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import tasks

from assistant.addons.base import Addon
from assistant.life_core import (
    MOOD_FACES,
    birthday_line,
    birthday_message,
    mood_reply,
    mood_summary,
    next_birthday,
    parse_birthday,
)
from assistant.tools import AssistantTool, ToolContext

log = logging.getLogger(__name__)

BIRTHDAY_HOUR = 9


class MoodButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"mood:(?P<score>[1-5]):(?P<day>\d{4}-\d{2}-\d{2})",
):
    def __init__(self, score: int, day: str):
        super().__init__(
            discord.ui.Button(
                label=str(score),
                emoji=MOOD_FACES[score],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mood:{score}:{day}",
            )
        )
        self.score = score
        self.day = day

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str]):
        return cls(int(match["score"]), match["day"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != interaction.client.settings.owner_id:
            await interaction.response.send_message("This assistant is private.", ephemeral=True)
            return
        cog = interaction.client.get_cog("Life")
        text = cog.log_mood(self.score, "", self.day) if cog else "Saved."
        await interaction.response.edit_message(view=None)
        await interaction.followup.send(text)


def mood_view(day: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for score in range(1, 6):
        view.add_item(MoodButton(score, day))
    return view


class Life(Addon):
    addon_name = "life"
    addon_description = "Daily mood check-ins and birthday reminders."

    birthdays = app_commands.Group(name="birthdays", description="Birthdays Patricia reminds you about")

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._busy = asyncio.Lock()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(MoodButton)
        self.ticker.start()

    async def cog_unload(self) -> None:
        self.ticker.cancel()
        self.bot.remove_dynamic_items(MoodButton)

    def _today(self) -> date:
        return datetime.now(self.bot.settings.timezone).date()

    # -------------------------------------------------------------- mood --

    def log_mood(self, score: int | None, note: str = "", day: str | None = None) -> str:
        day = day or self._today().isoformat()
        existing = self.bot.db.get_mood(day) or {}
        if score is None and not existing:
            return "Give me a number from 1 to 5 for today first."
        if score is not None:
            score = max(1, min(5, int(score)))
        self.bot.db.save_mood(day, score if score is not None else int(existing["score"]), note.strip()[:500] or existing.get("note") or "")
        if score is None:
            return "Added that to today's check-in. Thank you for telling me. 💜"
        since = (date.fromisoformat(day) - timedelta(days=6)).isoformat()
        recent = [int(r["score"]) for r in self.bot.db.moods_since(since)]
        self.bot.db.add_message(self.bot.settings.owner_id, "assistant", f"[Mood check-in: Joeii picked {score}/5 for {day}]")
        return mood_reply(score, recent)

    def mood_history(self, days: int = 7) -> str:
        since = (self._today() - timedelta(days=max(1, min(int(days or 7), 60)) - 1)).isoformat()
        rows = self.bot.db.moods_since(since)
        if not rows:
            return "No mood check-ins in that time."
        lines = [mood_summary(rows)]
        for row in rows:
            note = f": {row['note']}" if row.get("note") else ""
            lines.append(f"- {row['day']}: {row['score']}/5{note}")
        return "\n".join(lines)

    # --------------------------------------------------------- birthdays --

    def add_birthday(self, name: str, when: str, note: str = "") -> str:
        name = " ".join(name.split())[:60]
        if not name:
            return "Whose birthday is it?"
        try:
            month, day, year = parse_birthday(when)
        except ValueError:
            return "I couldn't read that date. Try 'March 3' or '3/3/2004'."
        row = self.bot.db.add_birthday(name, month, day, year, note.strip()[:200])
        return f"🎂 Saved: {birthday_line(row, self._today())}. I'll remind you 3 days before and on the day."

    def list_birthdays(self) -> str:
        today = self._today()
        rows = sorted(self.bot.db.list_birthdays(), key=lambda r: next_birthday(int(r["month"]), int(r["day"]), today))
        if not rows:
            return "No birthdays saved yet. Tell me like: Syl's birthday is March 3."
        return "\n".join(f"🎂 {birthday_line(r, today)}" for r in rows[:40])

    def remove_birthday(self, name: str) -> str:
        removed = self.bot.db.remove_birthday(name.strip())
        return f"Removed {removed}'s birthday." if removed else f"I don't have a birthday saved for {name}."

    # ------------------------------------------------------------- tools --

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="log_mood",
                description=(
                    "Save how Joeii's day went, 1 (awful) to 5 (great), with an optional note in his "
                    "words. Use when he rates his day or tells you how today went. To add a note to a "
                    "rating he already gave, leave score out."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "score": {"type": "integer", "minimum": 1, "maximum": 5},
                        "note": {"type": "string"},
                    },
                },
                handler=lambda ctx, score=None, note="": self.log_mood(score, note),
            ),
            AssistantTool(
                name="mood_history",
                description="Joeii's recent mood check-ins.",
                parameters={"type": "object", "properties": {"days": {"type": "integer"}}},
                handler=lambda ctx, days=7: self.mood_history(days),
            ),
            AssistantTool(
                name="add_birthday",
                description="Save someone's birthday so Patricia reminds Joeii 3 days before and on the day.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "date": {"type": "string", "description": "Like March 3, or 3/3/2004 if the year is known."},
                        "note": {"type": "string", "description": "Optional, like gift ideas."},
                    },
                    "required": ["name", "date"],
                },
                handler=lambda ctx, name, date, note="": self.add_birthday(name, date, note),
            ),
            AssistantTool(
                name="list_birthdays",
                description="List saved birthdays, soonest first.",
                parameters={"type": "object", "properties": {}},
                handler=lambda ctx: self.list_birthdays(),
            ),
            AssistantTool(
                name="remove_birthday",
                description="Remove a saved birthday by name. Only when Joeii asks.",
                parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
                handler=lambda ctx, name: self.remove_birthday(name),
            ),
        ]

    # ------------------------------------------------------------ ticker --

    @tasks.loop(minutes=2)
    async def ticker(self) -> None:
        if self._busy.locked():
            return
        async with self._busy:
            try:
                await self._mood_check_in()
                await self._birthday_reminders()
            except Exception:
                log.exception("Mood or birthday check failed")

    @ticker.before_loop
    async def before_ticker(self) -> None:
        await self.bot.wait_until_ready()

    async def _send(self, text: str, view: discord.ui.View | None = None) -> None:
        settings = self.bot.settings
        owner = self.bot.get_user(settings.owner_id) or await self.bot.fetch_user(settings.owner_id)
        if view is None:
            await owner.send(text)
        else:
            await owner.send(text, view=view)

    async def _mood_check_in(self) -> None:
        settings = self.bot.settings
        if not settings.mood_enabled:
            return
        now = datetime.now(settings.timezone)
        start = datetime.combine(now.date(), settings.mood_time, tzinfo=settings.timezone)
        if not start <= now < start + timedelta(hours=3):
            return
        day = now.date().isoformat()
        if self.bot.db.get_mood(day) or not self.bot.db.mark_daily("mood", day):
            return
        await self._send("💭 How was today, Joeii? Tap a number, and reply if you want to tell me more.", mood_view(day))
        self.bot.db.add_message(settings.owner_id, "assistant", "[Mood check-in sent: how was today, 1 to 5?]")

    async def _birthday_reminders(self) -> None:
        now = datetime.now(self.bot.settings.timezone)
        if now.hour < BIRTHDAY_HOUR:
            return
        today = now.date()
        for row in self.bot.db.list_birthdays():
            when = next_birthday(int(row["month"]), int(row["day"]), today)
            days = (when - today).days
            if days not in (0, 3):
                continue
            if not self.bot.db.mark_daily(f"birthday-{row['id']}-{days}", when.isoformat()):
                continue
            text = birthday_message(row, today, days)
            await self._send(text)
            self.bot.db.add_message(self.bot.settings.owner_id, "assistant", f"[Birthday reminder: {text}]")

    # ---------------------------------------------------------- commands --

    @app_commands.command(name="mood", description="Log how today went, 1 to 5")
    @app_commands.describe(score="1 (awful) to 5 (great)", note="Optional: what happened")
    async def mood_command(self, interaction: discord.Interaction, score: app_commands.Range[int, 1, 5], note: str = "") -> None:
        await interaction.response.send_message(self.log_mood(score, note))

    @birthdays.command(name="add", description="Save a birthday")
    @app_commands.describe(name="Whose birthday", date="Like March 3 or 3/3/2004", note="Optional, like gift ideas")
    async def birthday_add(self, interaction: discord.Interaction, name: str, date: str, note: str = "") -> None:
        await interaction.response.send_message(self.add_birthday(name, date, note))

    @birthdays.command(name="list", description="Saved birthdays, soonest first")
    async def birthday_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(self.list_birthdays()[:1900])

    @birthdays.command(name="remove", description="Remove a birthday")
    async def birthday_remove(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.send_message(self.remove_birthday(name))


async def setup(bot) -> None:
    await bot.add_cog(Life(bot))
