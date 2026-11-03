from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from assistant.addons.base import Addon
from assistant.brain import run_chat
from assistant.formatting import split_discord
from assistant.tools import ToolContext, collect_tools

log = logging.getLogger(__name__)


class Ask(Addon):
    addon_name = "questions"
    addon_description = "Answers questions and can use tools from the other addons."

    async def reply_to_text(self, user: discord.abc.User, text: str) -> str:
        cleaned = text.strip()[:4000]
        if not cleaned:
            return "Ask me something."
        if not self.bot.settings.xai_api_key:
            return (
                "Add XAI_API_KEY to the .env file, then restart the bot. "
                "Reminders and notes still work."
            )
        tools = collect_tools(self.bot)
        ctx = ToolContext(user.id, self.bot.settings, self.bot.db)
        history = self.bot.db.recent_messages(user.id, limit=12)
        try:
            answer = await asyncio.to_thread(
                run_chat, self.bot.settings, history, cleaned, tools, ctx
            )
        except Exception:
            log.exception("Question failed")
            return "That question failed. Check the bot window and the XAI_API_KEY in .env."
        self.bot.db.add_message(user.id, "user", cleaned)
        self.bot.db.add_message(user.id, "assistant", answer[:4000])
        return answer

    @app_commands.command(name="ask", description="Ask a question")
    @app_commands.describe(question="What you want to know or do")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.defer(ephemeral=True)
        answer = await self.reply_to_text(interaction.user, question)
        parts = split_discord(answer)
        await interaction.followup.send(parts[0], ephemeral=True)
        for part in parts[1:]:
            await interaction.followup.send(part, ephemeral=True)

    @app_commands.command(name="clear_chat", description="Forget the recent conversation")
    async def clear_chat(self, interaction: discord.Interaction) -> None:
        self.bot.db.clear_messages(interaction.user.id)
        await interaction.response.send_message(
            "Cleared our recent conversation. Notes and reminders stay.",
            ephemeral=True,
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
        async with message.channel.typing():
            answer = await self.reply_to_text(message.author, text)
        for part in split_discord(answer):
            await message.reply(part, mention_author=False)


async def setup(bot) -> None:
    await bot.add_cog(Ask(bot))
