from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import tasks

from assistant import pc
from assistant.addons.base import Addon
from assistant.bedtime_core import current_slot, night_window
from assistant.gaming_core import (
    MIN_SESSION_MINUTES,
    MISSES_TO_END,
    duration_text,
    minutes_between,
    one_more_text,
    total_minutes,
    week_start,
    wrap_up,
)
from assistant.tools import AssistantTool

log = logging.getLogger(__name__)

OVERTIME = timedelta(minutes=10)


class Gaming(Addon):
    addon_name = "gaming"
    addon_description = "Notices when you play, wraps up each session, and keeps you to 'one more game'."

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._busy = asyncio.Lock()
        self._misses = 0
        self._deadline: datetime | None = None   # one-more-game deadline, UTC
        self._nudged = 0                          # one-more-game nudges sent

    async def cog_load(self) -> None:
        self.watcher.start()

    async def cog_unload(self) -> None:
        self.watcher.cancel()

    # ------------------------------------------------------------ state --

    def _in_bedtime(self, now_local: datetime) -> bool:
        settings = self.bot.settings
        if not settings.bedtime_enabled:
            return False
        night, start_at, end_at = night_window(now_local, settings.bedtime_start, settings.bedtime_end)
        if current_slot(now_local, start_at, end_at, settings.bedtime_every) is None:
            return False
        row = self.bot.db.get_bedtime(night.isoformat()) or {}
        return not row.get("done_at")

    def start_one_more(self, minutes: int = 20) -> str:
        minutes = max(5, min(int(minutes or 20), 90))
        self._deadline = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        self._nudged = 0
        local = self._deadline.astimezone(self.bot.settings.timezone)
        hour = local.strftime("%I:%M %p").lstrip("0")
        return f"Deal: one more game. I'll check in at {hour} if you're still playing. 🎮"

    def stats(self) -> str:
        tz = self.bot.settings.timezone
        now = datetime.now(timezone.utc)
        now_local = now.astimezone(tz)
        since_week = week_start(now_local).astimezone(timezone.utc)
        since_day = datetime.combine(now_local.date(), datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
        sessions = self.bot.db.game_sessions_since(since_week - timedelta(days=1))
        today = total_minutes(sessions, since_day, now)
        week = total_minutes(sessions, since_week, now)
        open_row = self.bot.db.open_game_session()
        lines = [f"🎮 Today: **{duration_text(today)}** · This week: **{duration_text(week)}**"]
        if open_row:
            started = datetime.fromisoformat(open_row["started_at"])
            lines.append(f"Playing {open_row['game']} right now, for {duration_text(minutes_between(started, now))}.")
        longest = max(
            (minutes_between(datetime.fromisoformat(r["started_at"]), datetime.fromisoformat(r["ended_at"]))
             for r in sessions if r["ended_at"] and datetime.fromisoformat(r["started_at"]) >= since_week),
            default=0,
        )
        if longest:
            lines.append(f"Longest session this week: {duration_text(longest)}.")
        return "\n".join(lines)

    # ------------------------------------------------------------ tools --

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="one_more_game",
                description=(
                    "Start 'one more game' mode: if Joeii's game is still open after this many "
                    "minutes, Patricia pings him to wrap up. Use when he says one more game, last "
                    "game, or one more match."
                ),
                parameters={
                    "type": "object",
                    "properties": {"minutes": {"type": "integer", "description": "Default 20."}},
                },
                handler=lambda ctx, minutes=20: self.start_one_more(minutes),
            ),
            AssistantTool(
                name="gaming_stats",
                description="How long Joeii has played today and this week, and whether he's playing now.",
                parameters={"type": "object", "properties": {}},
                handler=lambda ctx: self.stats(),
            ),
        ]

    # ---------------------------------------------------------- watcher --

    @tasks.loop(seconds=60)
    async def watcher(self) -> None:
        if self._busy.locked() or not pc.is_windows():
            return
        async with self._busy:
            try:
                game = await asyncio.to_thread(pc.running_game, self.bot.settings)
                await self._update(game)
            except Exception:
                log.exception("Watching for games failed")

    @watcher.before_loop
    async def before_watcher(self) -> None:
        await self.bot.wait_until_ready()
        # A session left open by a shutdown ends when the game was last seen.
        row = self.bot.db.open_game_session()
        game = await asyncio.to_thread(pc.running_game, self.bot.settings)
        if row and not game:
            self.bot.db.end_game_session(row["id"], datetime.fromisoformat(row["last_seen_at"]))

    async def _send(self, text: str) -> None:
        settings = self.bot.settings
        owner = self.bot.get_user(settings.owner_id) or await self.bot.fetch_user(settings.owner_id)
        await owner.send(text)
        self.bot.db.add_message(settings.owner_id, "assistant", f"[Gaming: {text}]")

    async def _update(self, game: str | None) -> None:
        now = datetime.now(timezone.utc)
        row = self.bot.db.open_game_session()
        if game:
            self._misses = 0
            if row is None:
                self.bot.db.start_game_session(game, now)
                log.info("%s session started", game)
            else:
                self.bot.db.touch_game_session(row["id"], now)
            await self._check_one_more(game, now)
            return
        if row is None:
            return
        self._misses += 1
        if self._misses < MISSES_TO_END:
            return
        self._misses = 0
        ended = datetime.fromisoformat(row["last_seen_at"])
        self.bot.db.end_game_session(row["id"], ended)
        log.info("%s session ended", row["game"])
        promise = None
        if self._deadline is not None:
            promise = "kept" if ended <= self._deadline + timedelta(minutes=5) else "late"
            self._deadline = None
        started = datetime.fromisoformat(row["started_at"])
        if minutes_between(started, ended) < MIN_SESSION_MINUTES:
            return
        tz = self.bot.settings.timezone
        week = total_minutes(
            self.bot.db.game_sessions_since(week_start(now.astimezone(tz)).astimezone(timezone.utc) - timedelta(days=1)),
            week_start(now.astimezone(tz)).astimezone(timezone.utc),
            now,
        )
        text = wrap_up(row["game"], started.astimezone(tz), ended.astimezone(tz), week,
                       self._in_bedtime(now.astimezone(tz)), promise)
        await self._send(text)

    async def _check_one_more(self, game: str, now: datetime) -> None:
        if self._deadline is None:
            return
        if self._nudged == 0 and now >= self._deadline:
            self._nudged = 1
            await self._send(one_more_text(game, overtime=False))
        elif self._nudged == 1 and now >= self._deadline + OVERTIME:
            self._nudged = 2
            await self._send(one_more_text(game, overtime=True))

    # --------------------------------------------------------- commands --

    @app_commands.command(name="onemore", description="One more game: I'll ping you if you're still playing after it")
    @app_commands.describe(minutes="How long your one more game takes (default 20)")
    async def onemore_command(self, interaction: discord.Interaction, minutes: int = 20) -> None:
        await interaction.response.send_message(self.start_one_more(minutes))

    @app_commands.command(name="gaming", description="How long you've played today and this week")
    async def gaming_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(self.stats())


async def setup(bot) -> None:
    await bot.add_cog(Gaming(bot))
