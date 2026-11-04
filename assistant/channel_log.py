from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from assistant.formatting import split_discord

log = logging.getLogger(__name__)


def format_log(
    timezone: ZoneInfo,
    source: str,
    you: str = "",
    reply: str = "",
    now: datetime | None = None,
) -> str:
    moment = now or datetime.now(timezone)
    lines = [f"{source} · {moment.strftime('%b %d, %I:%M %p')}"]
    if you.strip():
        lines.append(f"You: {you.strip()}")
    if reply.strip():
        lines.append(f"Patricia: {reply.strip()}")
    return "\n".join(lines)


async def write_log(bot, text: str, *, origin_channel_id: int | None = None) -> None:
    channel_id = bot.settings.log_channel_id
    if channel_id is None or origin_channel_id == channel_id:
        return
    if not bot.is_ready():
        await bot.wait_until_ready()
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.HTTPException:
            log.warning("Could not open the log channel")
            return
    for part in split_discord(text):
        try:
            await channel.send(part)
        except discord.HTTPException:
            log.warning("Could not write to the log channel")
            return
