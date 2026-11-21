from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

from assistant.addons.base import Addon
from assistant.arrivals_core import (
    HOLD_LIMIT,
    describe,
    is_repeat,
    parse_ping,
    ping_text,
    place_key,
    place_label,
)
from assistant.channel_log import format_log, write_log
from assistant.tools import AssistantTool, ToolContext

log = logging.getLogger(__name__)

CHANNEL_PREF = "arrivals_channel_id"
WEBHOOK_NAME = "Patricia arrivals"


@dataclass
class Held:
    text: str
    at: datetime


class Arrivals(Addon):
    addon_name = "arrivals"
    addon_description = "Messages when your iPhone says you arrived at or left a place."

    arrival = app_commands.Group(name="arrival", description="Messages when you get to a place")

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._held: list[Held] = []

    async def cog_load(self) -> None:
        self.flusher.start()

    async def cog_unload(self) -> None:
        self.flusher.cancel()

    # ------------------------------------------------------------ state --

    def channel_id(self) -> int | None:
        raw = self.bot.db.get_pref(CHANNEL_PREF, "")
        return int(raw) if raw.isdigit() else None

    def set_message(self, place: str, text: str, kind: str = "arrive") -> str:
        label = place_label(place)
        key = place_key(label)
        if not key:
            return "That place needs a name, like home or school."
        if kind not in ("arrive", "leave"):
            kind = "arrive"
        text = " ".join(text.split())[:500]
        saved = self.bot.db.save_place_text(key, label, kind, text)
        verb = "get to" if kind == "arrive" else "leave"
        if not text:
            return f"Okay, nothing when you {verb} {saved['label']}."
        return (
            f"📍 Got it. When you {verb} {saved['label']}, I'll say: {text}\n"
            f"-# Your iPhone Shortcut sends: `{ping_text(kind, saved['label'])}`"
        )

    def remove(self, place: str) -> str:
        gone = self.bot.db.delete_place(place_key(place))
        if gone is None:
            return f"I don't have a place called {place}."
        return f"Removed {gone['label']}."

    def listing(self) -> str:
        places = self.bot.db.list_places()
        if not places:
            return "No places yet. Try `/arrival set place:school message:Park in lot B`."
        return "\n".join(describe(place) for place in places)

    async def _holding(self) -> bool:
        """Class quiet hours, when that feature is installed."""
        try:
            from assistant.quiet_core import holding
        except ImportError:
            return False
        try:
            result = holding(self.bot, "arrivals")
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception:
            log.exception("Quiet hours check failed, sending anyway")
            return False

    async def _dm(self, text: str) -> None:
        settings = self.bot.settings
        owner = self.bot.get_user(settings.owner_id) or await self.bot.fetch_user(settings.owner_id)
        await owner.send(text)
        self.bot.db.add_message(settings.owner_id, "assistant", f"[Arrival message: {text}]")

    # ------------------------------------------------------------ pings --

    async def handle_ping(self, kind: str, place: str, now: datetime | None = None) -> str:
        """Act on one ping. Returns what happened: sent, held, repeat, unknown, or silent."""
        now = now or datetime.now(timezone.utc)
        key = place_key(place)
        row = self.bot.db.get_place(key)
        if row is None:
            if kind != "arrive":
                return "silent"
            text = (
                f"📍 Your phone says you got to **{place_label(place)}**, but I don't have a message for it yet. "
                f"Use `/arrival set place:{place_label(place)}` or just tell me what to say."
            )
            await self._send_or_hold(text, now)
            return "unknown"
        if is_repeat(row.get(f"last_{kind}_at"), now):
            return "repeat"
        self.bot.db.mark_place(key, kind, now)
        message = row.get(f"{kind}_text") or ""
        if not message:
            return "silent"
        return await self._send_or_hold(f"📍 **{row['label']}**: {message}", now)

    async def _send_or_hold(self, text: str, now: datetime) -> str:
        if await self._holding():
            self._held.append(Held(text, now))
            log.info("Arrival message held for quiet hours")
            return "held"
        await self._dm(text)
        return "sent"

    @tasks.loop(seconds=60)
    async def flusher(self) -> None:
        if not self._held:
            return
        now = datetime.now(timezone.utc)
        self._held = [item for item in self._held if now - item.at < HOLD_LIMIT]
        if not self._held or await self._holding():
            return
        waiting, self._held = self._held, []
        for item in waiting:
            try:
                await self._dm(item.text)
            except Exception:
                log.exception("Could not send a held arrival message")

    @flusher.before_loop
    async def before_flusher(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        channel_id = self.channel_id()
        if channel_id is None or message.channel.id != channel_id or message.webhook_id is None:
            return
        parsed = parse_ping(message.content)
        if parsed is None:
            await self._react(message, "❔")
            return
        kind, place = parsed
        try:
            result = await self.handle_ping(kind, place)
        except Exception:
            log.exception("Arrival ping failed")
            await self._react(message, "⚠️")
            return
        log.info("Arrival ping %s %s: %s", kind, place_key(place), result)
        await self._react(
            message,
            {"sent": "✅", "held": "🤫", "repeat": "🔁", "unknown": "❔"}.get(result, "👍"),
        )
        await write_log(
            self.bot,
            format_log(self.bot.settings.timezone, "iPhone location", f"{kind} {place}", result),
            origin_channel_id=channel_id,
        )

    async def _react(self, message: discord.Message, emoji: str) -> None:
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------ tools --

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="set_arrival_message",
                description=(
                    "Save the message Patricia DMs Joeii when his iPhone says he arrived at (or left) a "
                    "place, like home or school. Use for 'when I get to school, remind me to ...'. "
                    "An empty message turns it off."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place": {"type": "string", "description": "Short place name, like home, school, or work"},
                        "message": {"type": "string", "description": "What to say when it happens"},
                        "when": {"type": "string", "enum": ["arrive", "leave"]},
                    },
                    "required": ["place", "message"],
                },
                handler=lambda ctx, place, message, when="arrive": self.set_message(place, message, when),
            ),
            AssistantTool(
                name="list_arrival_messages",
                description="List the places with arrival or leaving messages.",
                parameters={"type": "object", "properties": {}},
                handler=lambda ctx: self.listing(),
            ),
            AssistantTool(
                name="remove_arrival_place",
                description="Delete a place and its arrival and leaving messages.",
                parameters={
                    "type": "object",
                    "properties": {"place": {"type": "string"}},
                    "required": ["place"],
                },
                handler=lambda ctx, place: self.remove(place),
            ),
        ]

    # --------------------------------------------------------- commands --

    @arrival.command(name="setup", description="Use this channel for your iPhone's location pings")
    async def setup_command(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if interaction.guild is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Run this in a private text channel in your server, not in a DM.", ephemeral=True
            )
            return
        self.bot.db.set_pref(CHANNEL_PREF, str(channel.id))
        try:
            hook = await channel.create_webhook(name=WEBHOOK_NAME, reason="iPhone arrival pings")
        except discord.HTTPException:
            hook = None
        if hook is not None:
            text = (
                f"📍 This channel now gets your iPhone's arrival pings.\n"
                f"Copy this link into your Shortcut. Keep it secret, it lets anyone post here:\n{hook.url}"
            )
        else:
            text = (
                "📍 This channel now gets your iPhone's arrival pings.\n"
                "I'm not allowed to make the link myself, so:\n"
                "1. Long-press this channel, then Edit Channel.\n"
                "2. Integrations, then Webhooks, then New Webhook.\n"
                "3. Tap it and Copy Webhook URL. That link goes in your Shortcut."
            )
        await interaction.response.send_message(text, ephemeral=True)

    @arrival.command(name="set", description="Pick what I say when you get to (or leave) a place")
    @app_commands.describe(
        place="Short name, like home or school",
        message="What I DM you. Leave it out to turn this one off.",
        when="Arriving or leaving",
    )
    async def set_command(
        self,
        interaction: discord.Interaction,
        place: str,
        message: str = "",
        when: Literal["arrive", "leave"] = "arrive",
    ) -> None:
        await interaction.response.send_message(self.set_message(place, message, when))

    @arrival.command(name="list", description="Your places and their messages")
    async def list_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(self.listing())

    @arrival.command(name="remove", description="Delete a place")
    async def remove_command(self, interaction: discord.Interaction, place: str) -> None:
        await interaction.response.send_message(self.remove(place))

    @arrival.command(name="test", description="Send a place's message now, as if you just got there")
    async def test_command(
        self,
        interaction: discord.Interaction,
        place: str,
        when: Literal["arrive", "leave"] = "arrive",
    ) -> None:
        row = self.bot.db.get_place(place_key(place))
        message = (row or {}).get(f"{when}_text") or ""
        if not message:
            await interaction.response.send_message(f"There's no {when} message for {place} yet.", ephemeral=True)
            return
        await self._dm(f"📍 **{row['label']}**: {message}")
        await interaction.response.send_message("Sent it to your DMs.", ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Arrivals(bot))
