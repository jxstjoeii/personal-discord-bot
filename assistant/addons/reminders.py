from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import tasks

from assistant.addons.base import Addon
from assistant.channel_log import format_log, write_log
from assistant.formatting import format_stored, format_when, reminder_problem
from assistant.timeparse import PastTime, describe_every, next_due, parse_every, parse_when
from assistant.tools import AssistantTool, ToolContext

log = logging.getLogger(__name__)

WHEN_HELP = "Examples: in 20 minutes, tomorrow at 9am, friday 5pm."
EVERY_HELP = "Optional. Repeat it: 30 minutes, 2 hours, day, week."
UNTIL_HELP = "Optional. Stop repeating after this time: tonight at 10pm, friday."


def repeat_text(row: dict, tz) -> str:
    minutes = row.get("repeat_minutes")
    if not minutes:
        return ""
    text = describe_every(int(minutes))
    if row.get("until_at"):
        text += f" until {format_stored(row['until_at'], tz)}"
    return text


class Reminders(Addon):
    addon_name = "reminders"
    addon_description = "Personal reminders that arrive as a direct message."

    remind = app_commands.Group(name="remind", description="Set, list, and cancel reminders")

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="create_reminder",
                description=(
                    "Create a reminder that arrives as a Discord DM. Use whenever Joeii wants to "
                    "be reminded, nagged, or pinged about something, once or repeatedly. For "
                    "'every 30 minutes until I say stop', set every to '30 minutes', leave until "
                    "empty, and set when to the first time (usually 'in 30 minutes', or 'now' if "
                    "he wants one right away). Do not add quiet hours he did not ask for."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "when": {
                            "type": "string",
                            "description": "When to send the first one. " + WHEN_HELP + " Or now.",
                        },
                        "what": {
                            "type": "string",
                            "description": "What to remind them about.",
                        },
                        "every": {"type": "string", "description": EVERY_HELP},
                        "until": {"type": "string", "description": UNTIL_HELP},
                    },
                    "required": ["when", "what"],
                },
                handler=self._tool_create,
            ),
            AssistantTool(
                name="list_reminders",
                description="List the user's upcoming reminders, including repeating ones.",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=self._tool_list,
            ),
            AssistantTool(
                name="cancel_reminder",
                description=(
                    "Cancel one reminder by id, which also stops a repeating reminder. Use when "
                    "Joeii asks to cancel or stop it, or says he did the thing (done, stop, "
                    "listed it) in reply to that reminder. If it is unclear which one, list "
                    "them first and ask."
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

        tz = self.bot.settings.timezone
        now = datetime.now(timezone.utc)
        due = self.bot.db.due_reminders(now)
        for row in due:
            try:
                user = self.bot.get_user(row["user_id"])
                if user is None:
                    user = await self.bot.fetch_user(row["user_id"])
                when = format_stored(row["due_at"], tz)
                upcoming = None
                minutes = row.get("repeat_minutes")
                if minutes:
                    upcoming = next_due(datetime.fromisoformat(row["due_at"]), int(minutes), tz, now)
                    if row.get("until_at") and upcoming > datetime.fromisoformat(row["until_at"]):
                        upcoming = None
                lines = [f"Reminder: {row['text']}"]
                if minutes and upcoming is not None:
                    lines.append(
                        f"Repeats {describe_every(int(minutes))}. Next at "
                        f"{format_stored(upcoming.isoformat(), tz)}. Reply stop or done to end it."
                    )
                elif minutes:
                    lines.append("That was the last one.")
                else:
                    lines.append(f"Due {when}")
                await user.send("\n".join(lines))
                if upcoming is not None:
                    self.bot.db.reschedule_reminder(row["id"], upcoming)
                else:
                    self.bot.db.mark_reminder_sent(row["id"])
                # So Patricia knows what "stop" or "done" refers to.
                note = f"[I sent reminder #{row['id']}: {row['text']}"
                if minutes and upcoming is not None:
                    note += f". It repeats {describe_every(int(minutes))} until cancelled."
                self.bot.db.add_message(row["user_id"], "assistant", note + "]")
                log.info("Delivered reminder %s", row["id"])
                await write_log(
                    self.bot,
                    format_log(tz, "Reminder delivered", reply=f"#{row['id']} {row['text']}\nDue {when}"),
                )
            except discord.HTTPException:
                attempts = self.bot.db.bump_reminder_attempt(row["id"])
                log.warning("Could not deliver reminder %s (attempt %s)", row["id"], attempts)
                if attempts >= 5:
                    self.bot.db.mark_reminder_sent(row["id"])
                    log.warning("Stopped trying to deliver reminder %s", row["id"])

    def _tool_create(
        self, ctx: ToolContext, when: str, what: str, every: str = "", until: str = ""
    ) -> str:
        tz = ctx.settings.timezone
        problem = reminder_problem(what)
        if problem:
            return problem
        try:
            due = parse_when(when, tz)
        except PastTime as exc:
            return f"That time already passed ({format_when(exc.when, tz)})."
        except ValueError:
            return "I couldn't read that time. Try 'in 20 minutes' or 'tomorrow at 9am'."
        minutes = None
        if every and every.strip():
            try:
                minutes = parse_every(every)
            except ValueError:
                return "I couldn't read how often. Try '30 minutes', '2 hours', 'day', or 'week'."
        stop_at = None
        if until and until.strip():
            if minutes is None:
                return "Until only works with a repeating reminder. Say how often, too."
            try:
                stop_at = parse_when(until, tz)
            except (PastTime, ValueError):
                return "I couldn't read when to stop. Try 'tonight at 10pm' or 'friday'."
            if stop_at <= due:
                return "The stop time has to be after the first reminder."
        row = ctx.db.add_reminder(ctx.user_id, what, due, minutes, stop_at)
        text = f"Reminder #{row['id']} set for {format_stored(row['due_at'], tz)}: {row['text']}"
        if minutes:
            text += f". Repeats {repeat_text(row, tz)}."
            if not stop_at:
                text += " It keeps going until Joeii says stop."
        return text

    def _tool_list(self, ctx: ToolContext) -> str:
        rows = ctx.db.list_reminders(ctx.user_id)
        if not rows:
            return "No upcoming reminders."
        lines = []
        for row in rows[:15]:
            when = format_stored(row["due_at"], ctx.settings.timezone)
            repeat = repeat_text(row, ctx.settings.timezone)
            extra = f" (repeats {repeat})" if repeat else ""
            lines.append(f"#{row['id']} {when} — {row['text']}{extra}")
        return "\n".join(lines)

    def _tool_cancel(self, ctx: ToolContext, reminder_id: int) -> str:
        row = ctx.db.cancel_reminder(ctx.user_id, int(reminder_id))
        if row is None:
            return f"There is no upcoming reminder #{reminder_id}."
        return f"Cancelled reminder #{row['id']}: {row['text']}"

    @remind.command(name="add", description="Set a reminder")
    @app_commands.describe(
        when=WHEN_HELP, what="What to remind you about", every=EVERY_HELP, until=UNTIL_HELP
    )
    async def add(
        self,
        interaction: discord.Interaction,
        when: str,
        what: str,
        every: str | None = None,
        until: str | None = None,
    ) -> None:
        message = self._tool_create(self._ctx(interaction), when, what, every or "", until or "")
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
            repeat = repeat_text(row, tz)
            extra = f" · repeats {repeat}" if repeat else ""
            lines.append(f"**#{row['id']}** {when}{extra}\n{row['text']}")
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
