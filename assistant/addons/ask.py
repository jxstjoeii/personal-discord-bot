from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from assistant.addons.base import Addon
from assistant.brain import claude_status, run_chat
from assistant.channel_log import format_log, write_log
from assistant.formatting import format_stored, split_discord
from assistant.house import brief_report, calendar_report, direct_kind, weather_report
from assistant import hearing, pc_controls, vision
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
        images=None,
    ) -> str:
        return await self.reply_for_user(
            user.id,
            text,
            source=source,
            origin_channel_id=origin_channel_id,
            images=images,
        )

    async def reply_for_user(
        self,
        user_id: int,
        text: str,
        *,
        source: str = "Discord",
        origin_channel_id: int | None = None,
        images=None,
    ) -> str:
        cleaned = text.strip()[:4000]
        if not cleaned:
            return "Ask me something."
        kind = None if images else direct_kind(cleaned)
        instant = None if images else pc_controls.quick(cleaned)
        if instant is not None:
            # Simple PC controls happen right away, without waiting for Claude.
            answer = await asyncio.to_thread(pc_controls.run, *instant)
        elif kind is not None:
            answer = await asyncio.to_thread(self._direct, user_id, kind)
        elif not claude_status():
            answer = (
                "Chat needs Claude signed in. Run claude setup-token and put the token in CLAUDE_CODE_OAUTH_TOKEN in .env. "
                "Calendar, weather, reminders, and notes still work. Try /brief."
            )
        else:
            tools = collect_tools(self.bot)
            ctx = ToolContext(user_id, self.bot.settings, self.bot.db, origin_channel_id)
            history = self.bot.db.recent_messages(user_id, limit=12)
            try:
                answer = await asyncio.to_thread(
                    run_chat, self.bot.settings, history, cleaned, tools, ctx, images
                )
            except Exception:
                log.exception("Question failed")
                answer = (
                    "Something went wrong while I was answering, so I stopped. The details are in my log "
                    "(%LOCALAPPDATA%\\PatriciaBot\\bot.log). Calendar, weather, reminders, and notes still work."
                )
            else:
                saved = f"[sent {len(images)} picture(s)] {cleaned}" if images else cleaned
                self.bot.db.add_message(user_id, "user", saved)
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
        answer = await self.reply_to_text(
            interaction.user,
            question,
            source=source,
            origin_channel_id=interaction.channel_id,
        )
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

    async def _replied_to(self, message: discord.Message) -> discord.Message | None:
        """The message this one replies to, when it is one of Patricia's."""
        ref = message.reference
        if ref is None or ref.message_id is None:
            return None
        found = ref.resolved if isinstance(ref.resolved, discord.Message) else None
        if found is None:
            try:
                found = await message.channel.fetch_message(ref.message_id)
            except discord.HTTPException:
                return None
        if self.bot.user is None or found.author.id != self.bot.user.id:
            return None
        return found

    async def _voice(self, message: discord.Message) -> str:
        """Transcribes a voice message (or audio file) on this PC. Blank if there isn't one."""
        settings = self.bot.settings
        if not settings.voice_messages:
            return ""
        for attachment in message.attachments:
            kind = (attachment.content_type or "").split(";")[0].lower()
            if not kind.startswith("audio/") or attachment.size > 25_000_000:
                continue
            try:
                data = await attachment.read()
                async with message.channel.typing():
                    text = await asyncio.to_thread(
                        hearing.transcribe, data, settings.whisper_model, settings.whisper_device
                    )
            except hearing.HearingUnavailable as exc:
                await message.reply(f"I can't hear voice messages yet: {exc}", mention_author=False)
                return ""
            except Exception:
                log.exception("Transcribing a voice message failed")
                await message.reply("I couldn't make out that voice message. Could you try again?", mention_author=False)
                return ""
            if not text:
                await message.reply("I couldn't hear any words in that voice message.", mention_author=False)
            return text
        return ""

    async def _pictures(self, message: discord.Message):
        """Pictures attached to a message, shrunk for Claude, plus a note about any left out."""
        pictures = []
        left_out = 0
        for attachment in message.attachments:
            kind = (attachment.content_type or "").split(";")[0].lower()
            if not kind.startswith("image/"):
                continue
            if len(pictures) >= vision.MAX_IMAGES or attachment.size > 20_000_000:
                left_out += 1
                continue
            try:
                data = await attachment.read()
            except discord.HTTPException:
                left_out += 1
                continue
            picture = await asyncio.to_thread(vision.prepare, data, kind, attachment.filename)
            if picture is None:
                left_out += 1
            else:
                pictures.append(picture)
        note = ""
        if left_out:
            note = f"{left_out} picture(s) couldn't be used. I can look at up to {vision.MAX_IMAGES} at a time."
        return pictures, note

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.author.id != self.bot.settings.owner_id:
            return
        replied = await self._replied_to(message)
        if message.guild is not None:
            mentioned = self.bot.user is not None and self.bot.user in message.mentions
            listening = message.channel.id in self.bot.settings.chat_channel_ids
            if not (mentioned or listening or replied is not None):
                return
        text = message.content
        if self.bot.user is not None:
            text = text.replace(f"<@{self.bot.user.id}>", "")
            text = text.replace(f"<@!{self.bot.user.id}>", "")
        text = text.strip()
        heard = await self._voice(message)
        if heard:
            text = f"(voice message) {heard}" + (f"\n{text}" if text else "")
        images, skipped = await self._pictures(message)
        if not text and not images:
            if skipped:
                await message.reply(skipped, mention_author=False)
            return
        if not text:
            text = "(Joeii sent a picture without words. Say what you see and ask how you can help.)"
        if skipped:
            text += f"\n({skipped})"
        if replied is not None:
            quoted = replied.content or (replied.embeds[0].title if replied.embeds else "") or ""
            text = f'(Replying to Patricia\'s message: "{quoted[:600]}")\n{text}'
        source = "Discord DM" if message.guild is None else f"#{message.channel}"
        async with message.channel.typing():
            answer = await self.reply_to_text(
                message.author,
                text,
                source=source,
                origin_channel_id=message.channel.id,
                images=images,
            )
        if heard:
            answer = f"-# 🎙️ I heard: “{heard[:300]}”\n{answer}"
        for part in split_discord(answer):
            await message.reply(part, mention_author=False)


async def setup(bot) -> None:
    await bot.add_cog(Ask(bot))
