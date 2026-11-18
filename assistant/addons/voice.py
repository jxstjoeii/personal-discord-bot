from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord import app_commands

from assistant import hearing, pc
from assistant.addons.base import Addon
from assistant.formatting import split_discord
from assistant.tools import AssistantTool
from assistant.wake import WakeListener

log = logging.getLogger(__name__)

PREF = "listening"


class Voice(Addon):
    addon_name = "voice"
    addon_description = "Hears voice messages, and listens for 'Hey Patricia' on the PC when switched on."

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self.listener: WakeListener | None = None
        self._game_checked = 0.0
        self._game = False

    async def cog_load(self) -> None:
        settings = self.bot.settings
        if settings.voice_messages or settings.wake_word:
            # Load Whisper in the background so the first voice request isn't slow.
            asyncio.get_running_loop().run_in_executor(
                None, hearing.warm_up, settings.whisper_model, settings.whisper_device
            )
        if settings.wake_word and self.bot.db.get_pref(PREF) == "on":
            self._start()

    async def cog_unload(self) -> None:
        if self.listener:
            self.listener.stop()

    # ------------------------------------------------------------ switch --

    @property
    def listening(self) -> bool:
        return bool(self.listener and self.listener.running)

    def _paused(self) -> bool:
        """While a game runs, she doesn't respond (unless WAKE_DURING_GAMES=on)."""
        if self.bot.settings.wake_during_games:
            return False
        now = time.monotonic()
        if now - self._game_checked > 10:
            self._game = pc.running_game(self.bot.settings) is not None
            self._game_checked = now
        return self._game

    def _start(self) -> None:
        if self.listener is None:
            self.listener = WakeListener(self.bot.settings, self._on_request, self._paused)
        self.listener.start()

    def set_listening(self, on: bool) -> str:
        settings = self.bot.settings
        if not settings.wake_word:
            return "Hey Patricia is turned off in .env (WAKE_WORD=off)."
        if not pc.is_windows():
            return "Hey Patricia only works on the Windows PC."
        self.bot.db.set_pref(PREF, "on" if on else "off")
        if on:
            self._start()
            return (
                "👂 I'm listening for \"Hey Patricia\" now. Windows shows a microphone icon near the clock "
                "while I am. Say \"Hey Patricia, stop listening\" or use /listen off to stop."
                + (" I'll stay quiet while Overwatch is running." if not settings.wake_during_games else "")
            )
        if self.listener:
            self.listener.stop()
        return "🔇 Okay, I've stopped listening. The microphone is closed."

    def status(self) -> str:
        if not self.bot.settings.wake_word:
            return "Hey Patricia is turned off in .env."
        if self.listening:
            extra = " (paused while a game is running)" if self._paused() else ""
            return f"👂 Listening for \"Hey Patricia\"{extra}."
        problem = self.listener.problem if self.listener else ""
        if self.bot.db.get_pref(PREF) == "on" and problem:
            return f"I'm supposed to be listening, but: {problem}"
        return "🔇 Not listening. Use /listen on to turn it on."

    # ----------------------------------------------------------- request --

    def _on_request(self, text: str) -> str:
        """Called from the listener thread with what Joeii said."""
        loop = self.bot.loop
        ask = self.bot.get_cog("Ask")
        settings = self.bot.settings
        if ask is None:
            return "My chat isn't loaded."
        future = asyncio.run_coroutine_threadsafe(
            ask.reply_for_user(settings.owner_id, f"(said out loud) {text}", source="Hey Patricia"), loop
        )
        try:
            answer = future.result(timeout=240)
        except Exception:
            log.exception("Voice request failed")
            return "Sorry, something went wrong while I was answering."
        if settings.voice_dm:
            asyncio.run_coroutine_threadsafe(self._dm(f"🎙️ **You said:** {text}\n\n{answer}"), loop)
        return answer

    async def _dm(self, text: str) -> None:
        owner = self.bot.get_user(self.bot.settings.owner_id) or await self.bot.fetch_user(self.bot.settings.owner_id)
        for part in split_discord(text):
            await owner.send(part)

    # ------------------------------------------------------------- tools --

    def assistant_tools(self) -> list[AssistantTool]:
        if not self.bot.settings.wake_word:
            return []
        return [
            AssistantTool(
                name="set_listening",
                description=(
                    "Turn 'Hey Patricia' listening on the PC microphone on or off. Use when Joeii asks "
                    "you to start or stop listening, mute yourself, or stop using the mic."
                ),
                parameters={
                    "type": "object",
                    "properties": {"on": {"type": "boolean"}},
                    "required": ["on"],
                },
                handler=lambda ctx, on: self.set_listening(bool(on)),
            ),
            AssistantTool(
                name="listening_status",
                description="Whether 'Hey Patricia' listening is on.",
                parameters={"type": "object", "properties": {}},
                handler=lambda ctx: self.status(),
            ),
        ]

    # ---------------------------------------------------------- commands --

    @app_commands.command(name="listen", description="Turn 'Hey Patricia' listening on or off")
    @app_commands.choices(mode=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
        app_commands.Choice(name="status", value="status"),
    ])
    async def listen_command(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        if mode.value == "status":
            await interaction.response.send_message(self.status())
            return
        await interaction.response.send_message(self.set_listening(mode.value == "on"))
        status = self.bot.get_cog("Status")
        if status is not None:
            status._mood = None  # Show or hide the 👂 right away.


async def setup(bot) -> None:
    await bot.add_cog(Voice(bot))
