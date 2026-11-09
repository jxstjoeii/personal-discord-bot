from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "claude-sonnet-5-5"


class ConfigError(Exception):
    """The .env file is missing something the bot needs to start."""


@dataclass(frozen=True)
class Settings:
    discord_token: str
    owner_id: int
    guild_id: int | None
    anthropic_api_key: str
    model: str
    timezone: ZoneInfo
    database_path: Path
    user_addons_path: Path
    phone_token: str
    phone_port: int
    log_channel_id: int | None


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

    model = os.getenv("CLAUDE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    phone_token = os.getenv("PHONE_TOKEN", "").strip()
    phone_port_raw = os.getenv("PHONE_PORT", "8787").strip() or "8787"
    try:
        phone_port = int(phone_port_raw)
    except ValueError as exc:
        raise ConfigError("PHONE_PORT has to be a number, usually 8787.") from exc
    if not 1 <= phone_port <= 65535:
        raise ConfigError("PHONE_PORT has to be between 1 and 65535.")
    log_raw = os.getenv("LOG_CHANNEL_ID", "").strip()
    log_channel_id: int | None = None
    if log_raw:
        try:
            log_channel_id = int(log_raw)
        except ValueError as exc:
            raise ConfigError(
                "LOG_CHANNEL_ID has to be a numeric channel id, or leave it blank."
            ) from exc
    return Settings(
        discord_token=token,
        owner_id=owner_id,
        guild_id=guild_id,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        model=model,
        timezone=timezone,
        database_path=ROOT / "data" / "assistant.db",
        user_addons_path=ROOT / "user_addons",
        phone_token=phone_token,
        phone_port=phone_port,
        log_channel_id=log_channel_id,
    )
