from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import tasks

from assistant.addons.base import Addon
from assistant.channel_log import format_log, write_log
from assistant.formatting import format_stored, format_when, reminder_problem
from assistant.timeparse import PastTime, parse_when
from assistant.tools import AssistantTool, ToolContext

log = logging.getLogger(__name__)

WHEN_HELP = "Examples: in 20 minutes, tomorrow at 9am, friday 5pm."


class Reminders(Addon):
    addon_name = "reminders"
    addon_description = "Personal reminders that arrive as a direct message."

    remind = app_commands.Group(name="remind", description="Set, list, and cancel reminders")

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="create_reminder",
                description=(
                    "Create a reminder. Use when the user wants to be reminded "
                    "about something at a time."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "when": {
                            "type": "string",
                            "description": "When to send it. " + WHEN_HELP,
                        },
                        "what": {
                            "type": "string",
                            "description": "What to remind them about.",
                        },
                    },
                    "required": ["when", "what"],
                },
                handler=self._tool_create,
            ),
            AssistantTool(
                name="list_reminders",
                description="List the user's upcoming reminders.",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=self._tool_list,
            ),
            AssistantTool(
                name="cancel_reminder",
                description=(
                    "Cancel one reminder by id. Use only when the user clearly "
                    "asks to cancel that reminder."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "reminder_id": {
                            "type": "integer",
                            "description": "The reminder id from list_reminders.",
                        }
                    },
                    "required": ["reminder_id"],
                },
                handler=self._tool_cancel,
            ),
        ]

    async def cog_load(self) -> None:
        self.delivery.start()

    async def cog_unload(self) -> None:
        self.delivery.cancel()

    @tasks.loop(seconds=15)
    async def delivery(self) -> None:
        try:
            await self._deliver_due()
        except Exception:
            log.exception("Reminder delivery failed")

    @delivery.before_loop
    async def before_delivery(self) -> None:
        await self.bot.wait_until_ready()

    async def _deliver_due(self) -> None:
        from datetime import datetime, timezone

        due = self.bot.db.due_reminders(datetime.now(timezone.utc))
        for row in due:
            try:
                user = self.bot.get_user(row["user_id"])
                if user is None:
                    user = await self.bot.fetch_user(row["user_id"])
                when = format_stored(row["due_at"], self.bot.settings.timezone)
                await user.send(f"Reminder: {row['text']}\nDue {when}")
                self.bot.db.mark_reminder_sent(row["id"])
                log.info("Delivered reminder %s", row["id"])
                await write_log(
                    self.bot,
                    format_log(
                        self.bot.settings.timezone,
                        "Reminder delivered",
                        reply=f"#{row['id']} {row['text']}\nDue {when}",
                    ),
                )
            except discord.HTTPException:
                attempts = self.bot.db.bump_reminder_attempt(row["id"])
                log.warning(
                    "Could not deliver reminder %s (attempt %s)",
                    row["id"],
                    attempts,
                )
                if attempts >= 5:
                    self.bot.db.mark_reminder_sent(row["id"])
                    log.warning("Stopped trying to deliver reminder %s", row["id"])

    def _tool_create(self, ctx: ToolContext, when: str, what: str) -> str:
        problem = reminder_problem(what)
        if problem:
            return problem
        try:
            due = parse_when(when, ctx.settings.timezone)
        except PastTime as exc:
            return f"That time already passed ({format_when(exc.when, ctx.settings.timezone)})."
        except ValueError:
            return "I couldn't read that time. Try 'in 20 minutes' or 'tomorrow at 9am'."
        row = ctx.db.add_reminder(ctx.user_id, what, due)
        return (
            f"Reminder #{row['id']} set for "
            f"{format_stored(row['due_at'], ctx.settings.timezone)}: {row['text']}"
        )

    def _tool_list(self, ctx: ToolContext) -> str:
        rows = ctx.db.list_reminders(ctx.user_id)
        if not rows:
            return "No upcoming reminders."
        lines = []
        for row in rows[:15]:
            when = format_stored(row["due_at"], ctx.settings.timezone)
            lines.append(f"#{row['id']} {when} — {row['text']}")
        return "\n".join(lines)

    def _tool_cancel(self, ctx: ToolContext, reminder_id: int) -> str:
        row = ctx.db.cancel_reminder(ctx.user_id, int(reminder_id))
        if row is None:
            return f"There is no upcoming reminder #{reminder_id}."
        return f"Cancelled reminder #{row['id']}: {row['text']}"

    @remind.command(name="add", description="Set a reminder")
    @app_commands.describe(when=WHEN_HELP, what="What to remind you about")
    async def add(self, interaction: discord.Interaction, when: str, what: str) -> None:
        message = self._tool_create(self._ctx(interaction), when, what)
        await interaction.response.send_message(message)

    @remind.command(name="list", description="Show upcoming reminders")
    async def list_reminders(self, interaction: discord.Interaction) -> None:
        rows = self.bot.db.list_reminders(interaction.user.id)
        tz = self.bot.settings.timezone
        if not rows:
            await interaction.response.send_message(
                f"You have no reminders. Times use {tz.key}.",
            )
            return
        lines = [f"Times use {tz.key}."]
        for row in rows[:15]:
            when = format_stored(row["due_at"], tz)
            lines.append(f"**#{row['id']}** {when}\n{row['text']}")
        if len(rows) > 15:
            lines.append(f"{len(rows) - 15} more are saved.")
        await interaction.response.send_message("\n\n".join(lines)[:1900])

    @remind.command(name="cancel", description="Cancel a reminder by its id")
    @app_commands.describe(reminder_id="The id shown by /remind list")
    async def cancel(self, interaction: discord.Interaction, reminder_id: int) -> None:
        message = self._tool_cancel(self._ctx(interaction), reminder_id)
        await interaction.response.send_message(message)

    def _ctx(self, interaction: discord.Interaction) -> ToolContext:
        return ToolContext(interaction.user.id, self.bot.settings, self.bot.db)


async def setup(bot) -> None:
    await bot.add_cog(Reminders(bot))
