from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import tasks

from assistant.addons.base import Addon
from assistant.assignments_core import message, parse_due, pending
from assistant.formatting import format_stored, format_when
from assistant.timeparse import PastTime
from assistant.tools import AssistantTool, ToolContext

log = logging.getLogger(__name__)

DUE_HELP = "When it's due: friday 11:59pm, dec 3, tomorrow at noon. A day alone means 11:59 PM."


class DoneButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"hw:done:(?P<id>\d+)",
):
    def __init__(self, assignment_id: int):
        super().__init__(
            discord.ui.Button(
                label="Done",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=f"hw:done:{assignment_id}",
            )
        )
        self.assignment_id = assignment_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str]):
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != interaction.client.settings.owner_id:
            await interaction.response.send_message("This assistant is private.", ephemeral=True)
            return
        row = interaction.client.db.complete_assignment(interaction.user.id, self.assignment_id)
        await interaction.response.edit_message(view=None)
        if row is None:
            await interaction.followup.send("That one was already done or removed.")
        else:
            await interaction.followup.send(f"🎉 Nice work! **{row['title']}** is done.")


def done_view(assignment_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(DoneButton(assignment_id))
    return view


class Assignments(Addon):
    addon_name = "assignments"
    addon_description = "Tracks assignments and reminds you before they're due."

    hw = app_commands.Group(name="assignments", description="Your assignments and due dates")

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._busy = asyncio.Lock()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(DoneButton)
        self.checker.start()

    async def cog_unload(self) -> None:
        self.checker.cancel()
        self.bot.remove_dynamic_items(DoneButton)

    # ------------------------------------------------------------ tools --

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="add_assignment",
                description=(
                    "Track a school assignment, test, or project with a due date. Patricia reminds "
                    "Joeii 3 days before, the day before, the morning of, and 2 hours before. Use "
                    "this, not a reminder, for anything due for school."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short name, like History essay."},
                        "due": {"type": "string", "description": DUE_HELP},
                        "course": {"type": "string", "description": "Optional class name."},
                        "notes": {"type": "string", "description": "Optional details, like the prompt or page count."},
                    },
                    "required": ["title", "due"],
                },
                handler=self._tool_add,
            ),
            AssistantTool(
                name="list_assignments",
                description="List Joeii's open assignments, soonest due first.",
                parameters={"type": "object", "properties": {}},
                handler=self._tool_list,
            ),
            AssistantTool(
                name="complete_assignment",
                description="Mark an assignment done by id, which stops its reminders.",
                parameters={
                    "type": "object",
                    "properties": {"assignment_id": {"type": "integer"}},
                    "required": ["assignment_id"],
                },
                handler=self._tool_done,
            ),
            AssistantTool(
                name="change_assignment_due",
                description="Move an assignment's due date, for example when it gets extended.",
                parameters={
                    "type": "object",
                    "properties": {
                        "assignment_id": {"type": "integer"},
                        "due": {"type": "string", "description": DUE_HELP},
                    },
                    "required": ["assignment_id", "due"],
                },
                handler=self._tool_move,
            ),
            AssistantTool(
                name="remove_assignment",
                description="Delete an assignment by id. Only when Joeii clearly asks to remove it.",
                parameters={
                    "type": "object",
                    "properties": {"assignment_id": {"type": "integer"}},
                    "required": ["assignment_id"],
                },
                handler=self._tool_remove,
            ),
        ]

    def _parse(self, ctx: ToolContext, due: str):
        try:
            return parse_due(due, ctx.settings.timezone), None
        except PastTime as exc:
            return None, f"That date already passed ({format_when(exc.when, ctx.settings.timezone)})."
        except ValueError:
            return None, "I couldn't read that due date. Try 'friday 11:59pm' or 'dec 3'."

    def _tool_add(self, ctx: ToolContext, title: str, due: str, course: str = "", notes: str = "") -> str:
        title = title.strip()[:120]
        if not title:
            return "The assignment needs a name."
        moment, problem = self._parse(ctx, due)
        if problem:
            return problem
        row = ctx.db.add_assignment(ctx.user_id, title, course.strip()[:60], notes.strip()[:500], moment)
        return f"Assignment #{row['id']} tracked: {row['title']}, due {format_stored(row['due_at'], ctx.settings.timezone)}."

    def _tool_list(self, ctx: ToolContext) -> str:
        rows = ctx.db.list_assignments(ctx.user_id)
        if not rows:
            return "No open assignments."
        tz = ctx.settings.timezone
        lines = []
        for row in rows[:20]:
            course = f" ({row['course']})" if row.get("course") else ""
            lines.append(f"#{row['id']} {row['title']}{course}, due {format_stored(row['due_at'], tz)}")
        return "\n".join(lines)

    def _tool_done(self, ctx: ToolContext, assignment_id: int) -> str:
        row = ctx.db.complete_assignment(ctx.user_id, int(assignment_id))
        if row is None:
            return f"There is no open assignment #{assignment_id}."
        return f"Marked done: {row['title']}."

    def _tool_move(self, ctx: ToolContext, assignment_id: int, due: str) -> str:
        moment, problem = self._parse(ctx, due)
        if problem:
            return problem
        row = ctx.db.move_assignment(ctx.user_id, int(assignment_id), moment)
        if row is None:
            return f"There is no open assignment #{assignment_id}."
        return f"#{row['id']} {row['title']} is now due {format_stored(row['due_at'], ctx.settings.timezone)}."

    def _tool_remove(self, ctx: ToolContext, assignment_id: int) -> str:
        row = ctx.db.remove_assignment(ctx.user_id, int(assignment_id))
        if row is None:
            return f"There is no assignment #{assignment_id}."
        return f"Removed: {row['title']}."

    # ---------------------------------------------------------- checker --

    @tasks.loop(seconds=60)
    async def checker(self) -> None:
        if self._busy.locked():
            return
        async with self._busy:
            try:
                await self._remind()
            except Exception:
                log.exception("Assignment reminders failed")

    @checker.before_loop
    async def before_checker(self) -> None:
        await self.bot.wait_until_ready()

    async def _remind(self) -> None:
        settings = self.bot.settings
        tz = settings.timezone
        now = datetime.now(timezone.utc)
        for row in self.bot.db.open_assignments():
            sent = json.loads(row.get("sent") or "[]")
            due = datetime.fromisoformat(row["due_at"])
            created = datetime.fromisoformat(row["created_at"])
            key = pending(due, tz, sent, now, created)
            if key is None:
                continue
            sent.append(key)
            self.bot.db.mark_assignment_sent(row["id"], sent)
            text = message(key, row["title"], row.get("course") or "", format_stored(row["due_at"], tz))
            user = self.bot.get_user(row["user_id"]) or await self.bot.fetch_user(row["user_id"])
            await user.send(text, view=done_view(row["id"]))
            self.bot.db.add_message(row["user_id"], "assistant", f"[Assignment #{row['id']} reminder: {text}]")
            log.info("Assignment %s reminder %s sent", row["id"], key)

    # --------------------------------------------------------- commands --

    def _ctx(self, interaction: discord.Interaction) -> ToolContext:
        return ToolContext(interaction.user.id, self.bot.settings, self.bot.db)

    @hw.command(name="add", description="Track an assignment and get reminded before it's due")
    @app_commands.describe(title="Short name, like History essay", due=DUE_HELP, course="Optional class name")
    async def add_command(self, interaction: discord.Interaction, title: str, due: str, course: str | None = None) -> None:
        await interaction.response.send_message(self._tool_add(self._ctx(interaction), title, due, course or ""))

    @hw.command(name="list", description="Your open assignments")
    async def list_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(self._tool_list(self._ctx(interaction))[:1900])

    @hw.command(name="done", description="Mark an assignment done")
    @app_commands.describe(assignment_id="The id from /assignments list")
    async def done_command(self, interaction: discord.Interaction, assignment_id: int) -> None:
        await interaction.response.send_message(self._tool_done(self._ctx(interaction), assignment_id))


async def setup(bot) -> None:
    await bot.add_cog(Assignments(bot))
