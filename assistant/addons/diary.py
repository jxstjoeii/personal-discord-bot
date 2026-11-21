"""Diary: Patricia keeps what Joeii tells her about his day, by date, and can read it back.

Entries are stored in data/assistant.db (the data/ folder stays off GitHub).
This addon never sends messages on its own. It only answers, so class quiet hours don't apply.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

import discord
from discord import app_commands

from assistant.addons.base import Addon
from assistant.diary_core import clean_entry, day_label, format_entries, parse_day, prompt_card, prompts_for
from assistant.formatting import split_discord
from assistant.tools import AssistantTool

log = logging.getLogger(__name__)


class DiaryModal(discord.ui.Modal, title="📓 Diary"):
    def __init__(self, day: str, prompt: str):
        super().__init__(timeout=None)
        self.day = day
        self.prompt = prompt
        self.entry = discord.ui.TextInput(
            label=f"Diary for {date.fromisoformat(day).strftime('%a, %b %d')}",
            style=discord.TextStyle.paragraph,
            placeholder=prompt[:100],
            max_length=4000,
        )
        self.add_item(self.entry)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Diary")
        # The question is only a nudge in the box, so it isn't saved as the entry's prompt.
        text = cog.save_entry(str(self.entry.value), self.day) if cog else "Saved."
        await interaction.response.send_message(text)


class DiaryButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"diary:write:(?P<day>\d{4}-\d{2}-\d{2})",
):
    """'Write in my diary' button. Opens a box with one of today's questions."""

    def __init__(self, day: str):
        super().__init__(
            discord.ui.Button(
                label="Write in my diary",
                emoji="📓",
                style=discord.ButtonStyle.primary,
                custom_id=f"diary:write:{day}",
            )
        )
        self.day = day

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str]):
        return cls(match["day"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != interaction.client.settings.owner_id:
            await interaction.response.send_message("This assistant is private.", ephemeral=True)
            return
        await interaction.response.send_modal(DiaryModal(self.day, prompts_for(self.day, 1)[0]))


def diary_view(day: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(DiaryButton(day))
    return view


class Diary(Addon):
    addon_name = "diary"
    addon_description = "A private diary: what you tell her about your day, saved by date."

    diary = app_commands.Group(name="diary", description="Your private diary")

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(DiaryButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(DiaryButton)

    def _today(self) -> date:
        return datetime.now(self.bot.settings.timezone).date()

    def _day(self, when: str) -> date:
        return parse_day(when, self._today())

    # ------------------------------------------------------------ actions --

    def save_entry(self, text: str, day: str | None = None, prompt: str = "") -> str:
        text = clean_entry(text)
        if not text:
            return "There was nothing to save. Tell me about your day and I'll write it down."
        try:
            when = self._day(day) if day else self._today()
        except ValueError:
            return "I couldn't tell which day that's for. Try today, yesterday, or a date like 11/20."
        row = self.bot.db.add_diary(when.isoformat(), text, (prompt or "").strip()[:200])
        count = len(self.bot.db.diary_between(row["day"], row["day"]))
        which = "today" if when == self._today() else day_label(row["day"])
        extra = f" That's {count} entries for {which}." if count > 1 else ""
        self.bot.db.add_message(self.bot.settings.owner_id, "assistant", f"[Diary: saved entry #{row['id']} for {row['day']}]")
        return f"📓 Saved in your diary for {which}.{extra} Thanks for sharing it with me. 💜"

    def read(self, day: str = "", days: int | None = None, search: str = "") -> str:
        tz = self.bot.settings.timezone
        if search.strip():
            rows = self.bot.db.search_diary(search)
            if not rows:
                return f"Nothing in your diary mentions {search.strip()}."
            return format_entries(rows, tz)
        if days:
            span = max(1, min(int(days), 60))
            last = self._today()
            rows = self.bot.db.diary_between((last - timedelta(days=span - 1)).isoformat(), last.isoformat())
            if not rows:
                return f"No diary entries in the last {span} days."
            return format_entries(rows, tz)
        try:
            when = self._day(day)
        except ValueError:
            return "I couldn't read that date. Try today, yesterday, monday, or 11/20."
        rows = self.bot.db.diary_between(when.isoformat(), when.isoformat())
        if not rows:
            return f"No diary entry for {day_label(when.isoformat())}."
        text = format_entries(rows, tz)
        mood = self.bot.db.get_mood(when.isoformat())
        if mood:
            text += f"\nMood that day: {mood['score']}/5"
        return text

    def recent_days(self) -> str:
        rows = self.bot.db.diary_days(14)
        if not rows:
            return "Your diary is empty so far. Tell me about your day, or use /diary write."
        lines = ["📓 Days in your diary (newest first):"]
        lines += [f"• {day_label(r['day'])}: {r['entries']} entr{'y' if r['entries'] == 1 else 'ies'}" for r in rows]
        lines.append("Open one with /diary day, like: yesterday or 11/20.")
        return "\n".join(lines)

    def delete(self, entry_id: int) -> str:
        row = self.bot.db.delete_diary(int(entry_id))
        if not row:
            return f"There's no diary entry #{entry_id}."
        return f"Deleted diary entry #{entry_id} from {day_label(row['day'])}."

    # -------------------------------------------------------------- tools --

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="save_diary_entry",
                description=(
                    "Save something to Joeii's private diary. Use it whenever he tells you about his day, "
                    "what happened, or how he feels, especially after the evening check-in. Write it in "
                    "first person, in his own words, keeping the details and feelings (fix typos, but don't "
                    "shorten it into a summary). Leave day out for today; use 'yesterday' or a date if he's "
                    "talking about another day. If he answered one of the diary questions, put it in prompt."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "day": {"type": "string", "description": "today, yesterday, monday, or a date like 11/20"},
                        "prompt": {"type": "string", "description": "The diary question he answered, if any"},
                    },
                    "required": ["text"],
                },
                handler=lambda ctx, text, day="", prompt="": self.save_entry(text, day or None, prompt),
            ),
            AssistantTool(
                name="read_diary",
                description=(
                    "Read Joeii's diary. Give day for one day (today, yesterday, friday, 11/20), days for the "
                    "last N days, or search for words like a person's name. Use when he asks what happened "
                    "on a day, how he felt before, or when the last time something happened was."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "day": {"type": "string"},
                        "days": {"type": "integer"},
                        "search": {"type": "string"},
                    },
                },
                handler=lambda ctx, day="", days=None, search="": self.read(day, days, search),
            ),
            AssistantTool(
                name="diary_prompts",
                description="A few short questions and feeling words to help Joeii put his feelings into words.",
                parameters={"type": "object", "properties": {}},
                handler=lambda ctx: prompt_card(self._today().isoformat()),
            ),
        ]

    # ----------------------------------------------------------- commands --

    async def _answer(self, interaction: discord.Interaction, text: str, view: discord.ui.View | None = None) -> None:
        # In a server only Joeii sees it. In DMs it's private anyway.
        private = interaction.guild is not None
        parts = split_discord(text)
        if view is not None and len(parts) == 1:
            await interaction.response.send_message(parts[0], view=view, ephemeral=private)
            return
        await interaction.response.send_message(parts[0], ephemeral=private)
        for part in parts[1:]:
            await interaction.followup.send(part, ephemeral=private)

    @diary.command(name="write", description="Write a diary entry")
    @app_commands.describe(text="What happened, how you feel. Leave empty to get a writing box", day="Optional: yesterday, monday, 11/20")
    async def diary_write(self, interaction: discord.Interaction, text: str = "", day: str = "") -> None:
        if not text.strip():
            try:
                when = self._day(day).isoformat()
            except ValueError:
                await self._answer(interaction, "I couldn't read that date. Try today, yesterday, or 11/20.")
                return
            await interaction.response.send_modal(DiaryModal(when, prompts_for(when, 1)[0]))
            return
        await self._answer(interaction, self.save_entry(text, day or None))

    @diary.command(name="today", description="Read today's diary")
    async def diary_today(self, interaction: discord.Interaction) -> None:
        await self._answer(interaction, self.read("today"))

    @diary.command(name="day", description="Read the diary for one day")
    @app_commands.describe(day="yesterday, friday, 3 days ago, 11/20, or 2026-11-20")
    async def diary_day(self, interaction: discord.Interaction, day: str) -> None:
        await self._answer(interaction, self.read(day))

    @diary.command(name="week", description="Read the last 7 days of your diary")
    async def diary_week(self, interaction: discord.Interaction) -> None:
        await self._answer(interaction, self.read(days=7))

    @diary.command(name="list", description="Which days have diary entries")
    async def diary_list(self, interaction: discord.Interaction) -> None:
        await self._answer(interaction, self.recent_days())

    @diary.command(name="search", description="Find entries that mention something")
    @app_commands.describe(words="Like a name, a place, or a feeling")
    async def diary_search(self, interaction: discord.Interaction, words: str) -> None:
        await self._answer(interaction, self.read(search=words))

    @diary.command(name="prompts", description="A few short questions to help you name your feelings")
    async def diary_prompts(self, interaction: discord.Interaction) -> None:
        today = self._today().isoformat()
        await self._answer(interaction, prompt_card(today), view=diary_view(today))

    @diary.command(name="delete", description="Delete one diary entry by its number")
    @app_commands.describe(entry="The # number shown next to the entry")
    async def diary_delete(self, interaction: discord.Interaction, entry: int) -> None:
        await self._answer(interaction, self.delete(entry))


async def setup(bot) -> None:
    await bot.add_cog(Diary(bot))
