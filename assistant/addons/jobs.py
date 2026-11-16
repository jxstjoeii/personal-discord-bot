"""Scheduled jobs: Patricia does something on a schedule and tells Joeii what she found.

A reminder repeats a fixed message. A job thinks each time: it can check the
weather, the calendar, notes, or a web page, compare with what it found last
time, and only message Joeii when there is something worth saying.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import tasks

from assistant.addons.base import Addon
from assistant.brain import ClaudeUnavailable, claude_status
from assistant.channel_log import format_log, write_log
from assistant.formatting import format_stored, format_when, split_discord
from assistant.timeparse import PastTime, describe_every, next_due, parse_every, parse_when
from assistant.jobs_core import MAX_FAILURES, MIN_JOB_MINUTES, fetch_page, run_job
from assistant.tools import AssistantTool, ToolContext, collect_tools

log = logging.getLogger(__name__)

class Jobs(Addon):
    addon_name = "jobs"
    addon_description = "Scheduled jobs that check things and message you with what they find."

    jobs = app_commands.Group(name="jobs", description="Scheduled jobs Patricia runs for you")

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._running = asyncio.Lock()

    async def cog_load(self) -> None:
        self.runner.start()

    async def cog_unload(self) -> None:
        self.runner.cancel()

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="fetch_page",
                description="Read the text of a web page or JSON link. Read-only.",
                parameters={
                    "type": "object",
                    "properties": {"url": {"type": "string", "description": "The http or https link."}},
                    "required": ["url"],
                },
                handler=lambda ctx, url: fetch_page(url),
            ),
            AssistantTool(
                name="create_job",
                description=(
                    "Schedule a job that Patricia runs by herself, such as watching a web page for "
                    "a change, checking an order status, or a morning summary of weather and "
                    "calendar. Each run she does the work and only messages Joeii when there is "
                    "something worth saying. Use a reminder instead when he only wants a fixed "
                    "message repeated. Write the instruction so it makes sense on its own later, "
                    "with any link, and say when to message him and when the job is finished."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "instruction": {"type": "string", "description": "What to do on each run."},
                        "every": {
                            "type": "string",
                            "description": f"How often: 30 minutes, 2 hours, day, week. At least {MIN_JOB_MINUTES} minutes.",
                        },
                        "first": {
                            "type": "string",
                            "description": "When to run it first: now, in 1 hour, tomorrow at 8am. Defaults to now.",
                        },
                        "until": {"type": "string", "description": "Optional. Stop for good after this time."},
                    },
                    "required": ["instruction", "every"],
                },
                handler=self._tool_create,
            ),
            AssistantTool(
                name="list_jobs",
                description="List Joeii's scheduled jobs.",
                parameters={"type": "object", "properties": {}},
                handler=self._tool_list,
            ),
            AssistantTool(
                name="cancel_job",
                description="Stop a scheduled job by id. Use when Joeii asks to stop or cancel it.",
                parameters={
                    "type": "object",
                    "properties": {"job_id": {"type": "integer"}},
                    "required": ["job_id"],
                },
                handler=self._tool_cancel,
            ),
        ]

    # ------------------------------------------------------------ tools --

    def _tool_create(self, ctx: ToolContext, instruction: str, every: str, first: str = "now", until: str = "") -> str:
        tz = ctx.settings.timezone
        instruction = instruction.strip()
        if not instruction:
            return "The job needs an instruction."
        try:
            minutes = parse_every(every)
        except ValueError:
            return "I couldn't read how often. Try '30 minutes', '2 hours', 'day', or 'week'."
        if minutes < MIN_JOB_MINUTES:
            return f"Jobs can run at most every {MIN_JOB_MINUTES} minutes, to save your Claude usage. Use a reminder for faster pings."
        try:
            start = parse_when(first or "now", tz)
        except PastTime as exc:
            return f"That start time already passed ({format_when(exc.when, tz)})."
        except ValueError:
            return "I couldn't read when to start. Try 'now' or 'tomorrow at 8am'."
        stop_at = None
        if until and until.strip():
            try:
                stop_at = parse_when(until, tz)
            except (PastTime, ValueError):
                return "I couldn't read when to stop. Try 'friday' or 'in 3 days'."
        row = ctx.db.add_job(ctx.user_id, instruction, minutes, start, stop_at)
        text = (
            f"Job #{row['id']} runs {describe_every(minutes)}, first at "
            f"{format_stored(row['next_at'], tz)}: {instruction}"
        )
        if stop_at:
            text += f" It stops after {format_stored(row['until_at'], tz)}."
        return text

    def _tool_list(self, ctx: ToolContext) -> str:
        rows = ctx.db.list_jobs(ctx.user_id)
        if not rows:
            return "No scheduled jobs."
        tz = ctx.settings.timezone
        lines = []
        for row in rows[:15]:
            line = (
                f"#{row['id']} {describe_every(int(row['repeat_minutes']))}, next "
                f"{format_stored(row['next_at'], tz)} — {row['instruction']}"
            )
            if row.get("last_result"):
                line += f"\n   Last: {row['last_result'][:200]}"
            lines.append(line)
        return "\n".join(lines)

    def _tool_cancel(self, ctx: ToolContext, job_id: int) -> str:
        row = ctx.db.cancel_job(ctx.user_id, int(job_id))
        if row is None:
            return f"There is no active job #{job_id}."
        return f"Stopped job #{row['id']}: {row['instruction']}"

    # ----------------------------------------------------------- runner --

    @tasks.loop(seconds=30)
    async def runner(self) -> None:
        if self._running.locked():
            return
        async with self._running:
            try:
                await self._run_due()
            except Exception:
                log.exception("Running jobs failed")

    @runner.before_loop
    async def before_runner(self) -> None:
        await self.bot.wait_until_ready()

    async def _run_due(self) -> None:
        settings = self.bot.settings
        tz = settings.timezone
        now = datetime.now(timezone.utc)
        for job in self.bot.db.due_jobs(now):
            minutes = int(job["repeat_minutes"])
            upcoming = next_due(datetime.fromisoformat(job["next_at"]), minutes, tz, now)
            # Move it forward first, so a crash cannot make it run over and over.
            self.bot.db.update_job(job["id"], next_at=upcoming, last_run_at=now)
            last_one = bool(job.get("until_at")) and upcoming > datetime.fromisoformat(job["until_at"])
            if not claude_status():
                log.warning("Skipped job %s because Claude is not signed in", job["id"])
                continue
            ctx = ToolContext(job["user_id"], settings, self.bot.db)
            try:
                result = await asyncio.to_thread(run_job, settings, job, collect_tools(self.bot), ctx)
            except Exception as exc:
                await self._failed(job, exc)
                continue
            message = str(result.get("message") or "").strip()
            done = bool(result.get("done")) or last_one
            self.bot.db.update_job(
                job["id"],
                memory=str(result.get("remember") or "")[:4000],
                last_result=message[:1000],
                failures=0,
                active=0 if done else 1,
            )
            if result.get("notify") and message:
                footer = "This job is finished, so it won't run again." if done else (
                    f"Next check {format_stored(upcoming.isoformat(), tz)}."
                )
                await self._send(job["user_id"], f"**Job #{job['id']}**\n{message}\n-# {footer}")
                self.bot.db.add_message(job["user_id"], "assistant", f"[Job #{job['id']} reported: {message[:500]}]")
            elif done:
                await self._send(job["user_id"], f"**Job #{job['id']}** is finished: {job['instruction'][:300]}")
            await write_log(
                self.bot,
                format_log(tz, f"Job #{job['id']} ran", job["instruction"][:300], message or "Nothing to report."),
            )

    async def _failed(self, job: dict, exc: Exception) -> None:
        failures = int(job.get("failures") or 0) + 1
        detail = str(exc)[:300] if isinstance(exc, ClaudeUnavailable) else f"{type(exc).__name__}: {str(exc)[:250]}"
        log.warning("Job %s failed (%s in a row): %s", job["id"], failures, detail)
        if failures >= MAX_FAILURES:
            self.bot.db.update_job(job["id"], failures=failures, active=0)
            await self._send(
                job["user_id"],
                f"I paused job #{job['id']} after {failures} failed runs in a row.\n"
                f"Last problem: {detail}\nAsk me to set it up again when it's fixed.",
            )
        else:
            self.bot.db.update_job(job["id"], failures=failures)

    async def _send(self, user_id: int, text: str) -> None:
        user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
        for part in split_discord(text):
            await user.send(part)

    # --------------------------------------------------------- commands --

    @jobs.command(name="list", description="Show your scheduled jobs")
    async def list_command(self, interaction: discord.Interaction) -> None:
        text = self._tool_list(ToolContext(interaction.user.id, self.bot.settings, self.bot.db))
        await interaction.response.send_message(text[:1900])

    @jobs.command(name="cancel", description="Stop a scheduled job")
    @app_commands.describe(job_id="The id shown by /jobs list")
    async def cancel_command(self, interaction: discord.Interaction, job_id: int) -> None:
        text = self._tool_cancel(ToolContext(interaction.user.id, self.bot.settings, self.bot.db), job_id)
        await interaction.response.send_message(text)


async def setup(bot) -> None:
    await bot.add_cog(Jobs(bot))
