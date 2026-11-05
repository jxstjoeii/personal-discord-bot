from __future__ import annotations

import asyncio
from datetime import datetime

import discord
from discord import app_commands

from assistant.addons.base import Addon
from assistant.formatting import format_stored, split_discord
from assistant.house import brief_report, calendar_report, weather_report
from assistant.tools import AssistantTool, ToolContext

DAY_CHOICES = [
    app_commands.Choice(name="Today and tomorrow", value="both"),
    app_commands.Choice(name="Today", value="today"),
    app_commands.Choice(name="Tomorrow", value="tomorrow"),
]


class House(Addon):
    addon_name = "house"
    addon_description = "Reads the calendar and weather, and gives a short brief. The calendar is read-only."

    def assistant_tools(self) -> list[AssistantTool]:
        day_schema = {
            "type": "string",
            "enum": ["today", "tomorrow", "both"],
            "description": "Which day. Use both when they do not name a day.",
        }
        return [
            AssistantTool(
                name="calendar",
                description=(
                    "Read Joeii's calendar for today, tomorrow, or both. "
                    "Use this instead of guessing. The calendar cannot be changed."
                ),
                parameters={
                    "type": "object",
                    "properties": {"day": day_schema},
                    "required": [],
                },
                handler=self._tool_calendar,
            ),
            AssistantTool(
                name="weather",
                description="Read the weather at home for today, tomorrow, or both. Use this instead of guessing.",
                parameters={
                    "type": "object",
                    "properties": {"day": day_schema},
                    "required": [],
                },
                handler=self._tool_weather,
            ),
            AssistantTool(
                name="brief",
                description="Give the time, weather, calendar for today and tomorrow, and upcoming reminders.",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=self._tool_brief,
            ),
        ]

    def _tool_calendar(self, ctx: ToolContext, day: str = "both") -> str:
        return calendar_report(ctx.settings.timezone, datetime.now(ctx.settings.timezone), day)

    def _tool_weather(self, ctx: ToolContext, day: str = "both") -> str:
        return weather_report(ctx.settings.timezone, datetime.now(ctx.settings.timezone), day)

    def _tool_brief(self, ctx: ToolContext) -> str:
        return self._brief(ctx.settings.timezone, ctx.user_id, ctx.db)

    def _brief(self, zone, user_id: int, db) -> str:
        lines = []
        for row in db.list_reminders(user_id)[:5]:
            when = format_stored(row["due_at"], zone)
            lines.append(f"#{row['id']} {when} — {row['text']}")
        return brief_report(zone, datetime.now(zone), lines)

    async def _send(self, interaction: discord.Interaction, text: str) -> None:
        parts = split_discord(text)
        await interaction.followup.send(parts[0], ephemeral=True)
        for part in parts[1:]:
            await interaction.followup.send(part, ephemeral=True)

    @app_commands.command(name="brief", description="Time, weather, calendar, and reminders")
    async def brief(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        text = await asyncio.to_thread(
            self._brief,
            self.bot.settings.timezone,
            interaction.user.id,
            self.bot.db,
        )
        await self._send(interaction, text)

    @app_commands.command(name="calendar", description="Show today and tomorrow on the calendar")
    @app_commands.describe(day="Which day")
    @app_commands.choices(day=DAY_CHOICES)
    async def calendar(self, interaction: discord.Interaction, day: str = "both") -> None:
        await interaction.response.defer(ephemeral=True)
        text = await asyncio.to_thread(
            calendar_report,
            self.bot.settings.timezone,
            datetime.now(self.bot.settings.timezone),
            day,
        )
        await self._send(interaction, text)

    @app_commands.command(name="weather", description="Show the weather at home")
    @app_commands.describe(day="Which day")
    @app_commands.choices(day=DAY_CHOICES)
    async def weather(self, interaction: discord.Interaction, day: str = "both") -> None:
        await interaction.response.defer(ephemeral=True)
        text = await asyncio.to_thread(
            weather_report,
            self.bot.settings.timezone,
            datetime.now(self.bot.settings.timezone),
            day,
        )
        await self._send(interaction, text)


async def setup(bot) -> None:
    await bot.add_cog(House(bot))
