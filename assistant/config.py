from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
REASONING_LEVELS = ("none", "low", "medium", "high", "xhigh")


class ConfigError(Exception):
    """The .env file is missing something the bot needs to start."""


@dataclass(frozen=True)
class Settings:
    discord_token: str
    owner_id: int
    guild_id: int | None
    xai_api_key: str
    model: str
    reasoning_effort: str
    timezone: ZoneInfo
    database_path: Path
    user_addons_path: Path


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    token = os.getenv("DISCORD_TOKEN", "").strip()
    owner_raw = os.getenv("DISCORD_OWNER_ID", "").strip()
    if not token or not owner_raw:
        raise ConfigError(
            "Copy .env.example to .env and set DISCORD_TOKEN and DISCORD_OWNER_ID."
        )
    try:
        owner_id = int(owner_raw)
    except ValueError as exc:
        raise ConfigError(
            "DISCORD_OWNER_ID has to be the numeric id. In Discord, turn on "
            "Developer Mode, right-click your name, and choose Copy User ID."
        ) from exc

    guild_raw = os.getenv("DISCORD_GUILD_ID", "").strip()
    guild_id: int | None = None
    if guild_raw:
        try:
            guild_id = int(guild_raw)
        except ValueError as exc:
            raise ConfigError(
                "DISCORD_GUILD_ID has to be a numeric server id, or leave it blank."
            ) from exc

    timezone_name = os.getenv("TIMEZONE", "America/Los_Angeles").strip() or "America/Los_Angeles"
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(
            f"Unknown TIMEZONE {timezone_name!r}. Use an IANA name like America/Los_Angeles."
        ) from exc

    reasoning = os.getenv("XAI_REASONING", "low").strip().lower() or "low"
    if reasoning not in REASONING_LEVELS:
        joined = ", ".join(REASONING_LEVELS)
        raise ConfigError(f"XAI_REASONING must be one of: {joined}.")

    model = os.getenv("XAI_MODEL", "grok-4.7").strip() or "grok-4.7"
    return Settings(
        discord_token=token,
        owner_id=owner_id,
        guild_id=guild_id,
        xai_api_key=os.getenv("XAI_API_KEY", "").strip(),
        model=model,
        reasoning_effort=reasoning,
        timezone=timezone,
        database_path=ROOT / "data" / "assistant.db",
        user_addons_path=ROOT / "user_addons",
    )
