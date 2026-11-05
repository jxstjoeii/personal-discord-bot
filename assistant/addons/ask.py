from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from assistant.addons.base import Addon
from assistant.brain import run_chat
from assistant.channel_log import format_log, write_log
from assistant.formatting import format_stored, split_discord
from assistant.house import brief_report, calendar_report, direct_kind, weather_report
from assistant.tools import ToolContext, collect_tools

log = logging.getLogger(__name__)


class Ask(Addon):
    addon_name = "chat"
    addon_description = "Talks with Joeii and can use the calendar, weather, notes, and reminders."

    async def reply_to_text(
        self,
        user: discord.abc.User,
        text: str,
        *,
        source: str = "Discord",
        origin_channel_id: int | None = None,
    ) -> str:
        return await self.reply_for_user(
            user.id,
            text,
            source=source,
            origin_channel_id=origin_channel_id,
        )

    async def reply_for_user(
        self,
        user_id: int,
        text: str,
        *,
        source: str = "Discord",
        origin_channel_id: int | None = None,
    ) -> str:
        cleaned = text.strip()[:4000]
        if not cleaned:
            return "Ask me something."
        kind = direct_kind(cleaned)
        if kind is not None:
            answer = await asyncio.to_thread(self._direct, user_id, kind)
        elif not self.bot.settings.xai_api_key:
            answer = (
                "Chat needs an XAI_API_KEY in the .env file. "
                "Calendar, weather, reminders, and notes still work. Try /brief."
            )
        else:
            tools = collect_tools(self.bot)
            ctx = ToolContext(user_id, self.bot.settings, self.bot.db)
            history = self.bot.db.recent_messages(user_id, limit=12)
            try:
                answer = await asyncio.to_thread(
                    run_chat, self.bot.settings, history, cleaned, tools, ctx
                )
            except Exception:
                log.exception("Question failed")
                answer = (
                    "Chat could not reach Grok. Check XAI_API_KEY in .env. "
                    "Calendar, weather, reminders, and notes still work."
                )
            else:
                self.bot.db.add_message(user_id, "user", cleaned)
                self.bot.db.add_message(user_id, "assistant", answer[:4000])
        await write_log(
            self.bot,
            format_log(self.bot.settings.timezone, source, cleaned, answer),
            origin_channel_id=origin_channel_id,
        )
        return answer

    def _direct(self, user_id: int, kind: str) -> str:
        zone = self.bot.settings.timezone
        now = datetime.now(zone)
        if kind == "calendar":
            return calendar_report(zone, now, "both")
        if kind == "weather":
            return weather_report(zone, now, "both")
        lines = []
        for row in self.bot.db.list_reminders(user_id)[:5]:
            when = format_stored(row["due_at"], zone)
            lines.append(f"#{row['id']} {when} — {row['text']}")
        return brief_report(zone, now, lines)

    async def _answer(self, interaction: discord.Interaction, question: str, source: str) -> None:
        await interaction.response.defer()
        answer = await self.reply_to_text(interaction.user, question, source=source)
        parts = split_discord(answer)
        await interaction.followup.send(parts[0])
        for part in parts[1:]:
            await interaction.followup.send(part)

    @app_commands.command(name="chat", description="Chat with Patricia")
    @app_commands.describe(message="What you want to say")
    async def chat(self, interaction: discord.Interaction, message: str) -> None:
        await self._answer(interaction, message, "/chat")

    @app_commands.command(name="ask", description="Ask Patricia something")
    @app_commands.describe(question="What you want to know or do")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        await self._answer(interaction, question, "/ask")

    @app_commands.command(name="clear_chat", description="Forget the recent conversation")
    async def clear_chat(self, interaction: discord.Interaction) -> None:
        self.bot.db.clear_messages(interaction.user.id)
        await interaction.response.send_message(
            "Cleared our recent conversation. Notes and reminders stay.",
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.author.id != self.bot.settings.owner_id:
            return
        mentioned = self.bot.user is not None and self.bot.user in message.mentions
        if message.guild is not None and not mentioned:
            return
        text = message.content
        if self.bot.user is not None:
            text = text.replace(f"<@{self.bot.user.id}>", "")
            text = text.replace(f"<@!{self.bot.user.id}>", "")
        text = text.strip()
        if not text:
            return
        source = "Discord DM" if message.guild is None else f"#{message.channel}"
        async with message.channel.typing():
            answer = await self.reply_to_text(
                message.author,
                text,
                source=source,
                origin_channel_id=message.channel.id,
            )
        for part in split_discord(answer):
            await message.reply(part, mention_author=False)


async def setup(bot) -> None:
    await bot.add_cog(Ask(bot))
