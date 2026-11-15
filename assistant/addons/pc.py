from __future__ import annotations

import asyncio
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from assistant import pc
from assistant.brain import claude_status
from assistant.addons.base import Addon
from assistant.channel_log import format_log, write_log
from assistant.tools import AssistantTool, ToolContext

log = logging.getLogger(__name__)

EXPIRES = timedelta(minutes=60)
RISK_LABEL = {"low": "Low", "medium": "Medium", "high": "High: read the commands carefully"}


def _code(text: str, limit: int) -> str:
    text = text.replace("```", "'''")
    if len(text) > limit:
        text = text[: limit - 12].rstrip() + "\n…(cut off)"
    return f"```powershell\n{text}\n```"


def plan_embed(plan: dict, task_id: int) -> tuple[discord.Embed, discord.File | None]:
    attempt = int(plan.get("attempt", 1))
    title = "Run this on your PC?" if attempt == 1 else f"Try this fix? (attempt {attempt})"
    lines = [plan.get("summary") or plan.get("goal", ""), ""]
    for number, step in enumerate(plan["commands"], start=1):
        lines.append(f"**{number}. {step['description']}**")
        lines.append(_code(step["command"], 900))
    description = "\n".join(lines)
    file = None
    if len(description) > 3800:
        # Too long to show in full, so the full script comes along as a file.
        short = [plan.get("summary") or plan.get("goal", ""), ""]
        short += [f"**{n}. {s['description']}**" for n, s in enumerate(plan["commands"], start=1)]
        short.append("\nThe full commands are in the attached file. Read it before you press Yes.")
        description = "\n".join(short)[:3800]
        script = "\n\n".join(f"# {n}. {s['description']}\n{s['command']}" for n, s in enumerate(plan["commands"], 1))
        file = discord.File(io.BytesIO(script.encode("utf-8")), filename=f"plan-{task_id}.ps1")
    risk = plan.get("risk", "medium")
    color = discord.Color.red() if risk == "high" else discord.Color.orange() if risk == "medium" else discord.Color.blurple()
    embed = discord.Embed(title=title, description=description, color=color)
    embed.add_field(name="Risk", value=RISK_LABEL.get(risk, risk), inline=True)
    if plan.get("needs_admin"):
        embed.add_field(
            name="Administrator",
            value="This needs administrator rights. Patricia runs as your normal account, so it will probably fail.",
            inline=False,
        )
    if plan.get("verify_command"):
        embed.add_field(name="Then checks with", value=_code(plan["verify_command"], 900), inline=False)
    if plan.get("game"):
        embed.add_field(
            name=f"{plan['game']} is running",
            value="Anything that opens goes on the screen Discord is on, not your game screen.",
            inline=False,
        )
    embed.set_footer(text=f"Task {task_id} · Nothing runs until you press Yes · Expires in 60 minutes")
    return embed, file


def result_embed(plan: dict, report: pc.RunReport, verdict: dict | None, task_id: int) -> discord.Embed:
    if report.refused:
        embed = discord.Embed(title="Not run", description=report.refused, color=discord.Color.red())
    elif verdict is None:
        ok = report.all_ok
        embed = discord.Embed(
            title="Finished" if ok else "Something failed",
            description="Patricia could not check the result with Claude. Here is the raw output.",
            color=discord.Color.green() if ok else discord.Color.red(),
        )
    else:
        ok = verdict["success"]
        lines = [verdict.get("summary", "")]
        if not ok and verdict.get("problem"):
            lines += ["", f"**What went wrong:** {verdict['problem']}"]
        if not ok and verdict.get("fix"):
            lines += ["", f"**How to fix it:** {verdict['fix']}"]
        embed = discord.Embed(
            title="Done" if ok else "That didn't work",
            description="\n".join(lines)[:3800],
            color=discord.Color.green() if ok else discord.Color.red(),
        )
    for number, step in enumerate(report.steps, start=1):
        mark = "✅" if step.ok else "❌"
        shown = step.error if not step.ok and step.error else step.output
        value = _code(shown, 300) if shown else "No output."
        embed.add_field(name=f"{mark} {number}. {step.description}"[:250], value=value, inline=False)
    skipped = len(plan.get("commands", [])) - len(report.steps)
    if skipped > 0 and not report.refused:
        embed.add_field(name="Skipped", value=f"{skipped} later step(s) did not run.", inline=False)
    if report.check is not None:
        shown = report.check.output or report.check.error
        embed.add_field(name="Check", value=_code(shown, 400) if shown else "No output.", inline=False)
    embed.set_footer(text=f"Task {task_id} · Goal: {plan.get('goal', '')}"[:2000])
    return embed


class PcButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"pc:(?P<action>yes|no):(?P<task>\d+)",
):
    def __init__(self, action: str, task_id: int):
        super().__init__(
            discord.ui.Button(
                label="Yes, run it" if action == "yes" else "No",
                style=discord.ButtonStyle.success if action == "yes" else discord.ButtonStyle.danger,
                custom_id=f"pc:{action}:{task_id}",
            )
        )
        self.action = action
        self.task_id = task_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item, match: re.Match[str]):
        return cls(match["action"], int(match["task"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("PcTasks")
        if cog is None:
            await interaction.response.send_message("The PC ability is not loaded.", ephemeral=True)
            return
        await cog.handle_click(interaction, self.action, self.task_id)


def approval_view(task_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(PcButton("yes", task_id))
    view.add_item(PcButton("no", task_id))
    return view


class PcTasks(Addon):
    addon_name = "pc"
    addon_description = (
        "Plans PowerShell commands for something you want done on this PC, "
        "and runs them only after you press Yes."
    )

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(PcButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(PcButton)

    def assistant_tools(self) -> list[AssistantTool]:
        if not self.bot.settings.pc_enabled:
            return []
        return [
            AssistantTool(
                name="propose_pc_task",
                description=(
                    "Use when Joeii wants something done on his PC that commands could do, such as "
                    "opening an app or folder, changing a setting, moving files, or checking disk "
                    "space. This plans PowerShell commands and sends them to Discord with Yes and No "
                    "buttons. Nothing runs until he presses Yes. After it returns, tell him briefly "
                    "to look at the message and press Yes or No. Do not repeat the commands."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "What Joeii wants to end up true on his PC, in his words plus any details from the chat.",
                        }
                    },
                    "required": ["goal"],
                },
                handler=self._tool_propose,
            )
        ]

    def _tool_propose(self, ctx: ToolContext, goal: str) -> str:
        future = asyncio.run_coroutine_threadsafe(
            self.propose(ctx.user_id, goal, ctx.channel_id), self.bot.loop
        )
        try:
            return future.result(timeout=240)
        except Exception as exc:
            log.exception("Planning a PC task failed")
            return json.dumps({"error": f"Could not plan that: {exc}"})

    async def _destination(self, channel_id: int | None):
        if channel_id is not None:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except discord.HTTPException:
                    channel = None
            if channel is not None:
                return channel
        owner = self.bot.get_user(self.bot.settings.owner_id) or await self.bot.fetch_user(
            self.bot.settings.owner_id
        )
        return owner.dm_channel or await owner.create_dm()

    async def send_plan(self, user_id: int, plan: dict, channel_id: int | None) -> discord.Message:
        task_id = self.bot.db.add_pc_task(user_id, json.dumps(plan), channel_id)
        embed, file = plan_embed(plan, task_id)
        channel = await self._destination(channel_id)
        kwargs = {"embed": embed, "view": approval_view(task_id)}
        if file is not None:
            kwargs["file"] = file
        message = await channel.send(**kwargs)
        self.bot.db.set_pc_task_message(task_id, message.channel.id, message.id)
        return message

    async def propose(self, user_id: int, goal: str, channel_id: int | None) -> str:
        """Plan the task and post it for approval. Returns text for the chat reply."""
        settings = self.bot.settings
        if not settings.pc_enabled:
            return "PC commands are turned off. Set PC_COMMANDS=on in .env to use them."
        if not claude_status():
            return "Planning PC commands needs Claude signed in. Run claude setup-token and put the token in CLAUDE_CODE_OAUTH_TOKEN in .env."
        plan = await asyncio.to_thread(pc.plan_task, settings, goal)
        if not plan["possible"]:
            reason = plan["reason"] or "I could not find commands that would do that safely."
            return f"I can't do that with commands. {reason}"
        await self.send_plan(user_id, plan, channel_id)
        return "I sent the plan to Discord with Yes and No buttons. Nothing runs until Joeii presses Yes."

    @app_commands.command(name="pc", description="Have Patricia do something on this PC, after you approve")
    @app_commands.describe(task="What you want to happen on your PC")
    async def pc_command(self, interaction: discord.Interaction, task: str) -> None:
        settings = self.bot.settings
        if not settings.pc_enabled:
            await interaction.response.send_message("PC commands are turned off. Set PC_COMMANDS=on in .env.")
            return
        if not claude_status():
            await interaction.response.send_message(
                "Planning PC commands needs Claude signed in. Run claude setup-token and put the token in CLAUDE_CODE_OAUTH_TOKEN in .env."
            )
            return
        await interaction.response.defer(thinking=True)
        try:
            plan = await asyncio.to_thread(pc.plan_task, settings, task.strip()[:1500])
        except Exception:
            log.exception("Planning a PC task failed")
            await interaction.followup.send("I couldn't reach Claude to plan that. Check CLAUDE_CODE_OAUTH_TOKEN in .env, or the bot window for details.")
            return
        if not plan["possible"]:
            reason = plan["reason"] or "I could not find commands that would do that safely."
            await interaction.followup.send(f"I can't do that with commands. {reason}")
            return
        task_id = self.bot.db.add_pc_task(interaction.user.id, json.dumps(plan), interaction.channel_id)
        embed, file = plan_embed(plan, task_id)
        kwargs = {"embed": embed, "view": approval_view(task_id), "wait": True}
        if file is not None:
            kwargs["file"] = file
        message = await interaction.followup.send(**kwargs)
        self.bot.db.set_pc_task_message(task_id, message.channel.id, message.id)

    async def handle_click(self, interaction: discord.Interaction, action: str, task_id: int) -> None:
        settings = self.bot.settings
        if interaction.user.id != settings.owner_id:
            await interaction.response.send_message("This assistant is private.", ephemeral=True)
            return
        row = self.bot.db.get_pc_task(task_id)
        if row is None:
            await interaction.response.send_message("I can't find that plan anymore.", ephemeral=True)
            return
        plan = json.loads(row["plan"])

        if action == "no":
            self.bot.db.claim_pc_task(task_id, "pending", "cancelled")
            await interaction.response.defer()
            try:
                await interaction.delete_original_response()
            except discord.HTTPException:
                if interaction.message is not None:
                    await interaction.message.delete()
            await write_log(self.bot, format_log(settings.timezone, "/pc cancelled", plan.get("goal", "")))
            return

        created = datetime.fromisoformat(row["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - created > EXPIRES:
            self.bot.db.claim_pc_task(task_id, "pending", "expired")
            await interaction.response.edit_message(
                content="This plan expired, so nothing ran. Ask again for a fresh one.", view=None
            )
            return
        if not self.bot.db.claim_pc_task(task_id, "pending", "running"):
            await interaction.response.send_message(
                f"That plan is already {row['status']}.", ephemeral=True
            )
            return

        running = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
        if running is not None:
            running.title = "Running…"
            running.set_footer(text=f"Task {task_id} · Started")
        await interaction.response.edit_message(embed=running, view=None)

        report = await asyncio.to_thread(pc.run_plan, settings, plan)
        verdict = None
        if not report.refused:
            try:
                verdict = await asyncio.to_thread(pc.judge, settings, plan, report)
            except Exception:
                log.exception("Checking a PC task failed")
        success = bool(verdict["success"]) if verdict else report.all_ok and not report.refused
        self.bot.db.claim_pc_task(task_id, "running", "done" if success else "failed")
        await interaction.edit_original_response(embed=result_embed(plan, report, verdict, task_id), view=None)
        await write_log(
            self.bot,
            format_log(
                settings.timezone,
                "/pc ran",
                plan.get("goal", ""),
                "Worked." if success else (verdict or {}).get("problem") or report.refused or "Failed.",
            ),
        )

        followup = pc.fix_plan(plan, verdict) if verdict else None
        if followup is not None and int(followup.get("attempt", 2)) <= 4:
            try:
                await self.send_plan(interaction.user.id, followup, interaction.channel_id)
            except Exception:
                log.exception("Sending the fix failed")


async def setup(bot) -> None:
    await bot.add_cog(PcTasks(bot))
