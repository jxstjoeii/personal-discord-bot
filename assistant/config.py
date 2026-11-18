from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "sonnet"


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
    pc_enabled: bool = True
    chat_channel_ids: tuple[int, ...] = ()
    openrouter_model: str = "openrouter/auto"
    bedtime_enabled: bool = True
    bedtime_start: time = time(20, 30)
    bedtime_end: time = time(4, 0)
    bedtime_every: int = 30
    meds_enabled: bool = True
    meds_start: time = time(9, 0)
    meds_until: time = time(13, 0)
    meds_every: int = 60
    meds_name: str = ""
    morning_enabled: bool = True
    morning_time: time = time(8, 0)
    voice_messages: bool = True
    wake_word: bool = True
    wake_during_games: bool = False
    voice_replies: bool = True
    voice_dm: bool = True
    whisper_model: str = "small.en"
    wake_model: str = "tiny.en"
    whisper_device: str = "cpu"
    mic_device: str = ""
    voice_name: str = "af_heart"
    kokoro_python: str = ""
    kokoro_models: str = ""
    pc_timeout: int = 120
    quiet_games: tuple[str, ...] = ("Overwatch",)


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    # A blank line in .env would still count as "set" for Claude Code, and an
    # API key, even an empty one, outranks the subscription token.
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY"):
        if name in os.environ and not os.environ[name].strip():
            del os.environ[name]
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
    pc_raw = os.getenv("PC_COMMANDS", "on").strip().lower() or "on"
    if pc_raw not in ("on", "off"):
        raise ConfigError("PC_COMMANDS has to be on or off.")
    timeout_raw = os.getenv("PC_COMMAND_TIMEOUT", "120").strip() or "120"
    try:
        pc_timeout = int(timeout_raw)
    except ValueError as exc:
        raise ConfigError("PC_COMMAND_TIMEOUT has to be a number of seconds, like 120.") from exc
    if not 5 <= pc_timeout <= 1800:
        raise ConfigError("PC_COMMAND_TIMEOUT has to be between 5 and 1800 seconds.")
    games_raw = os.getenv("QUIET_GAMES", "Overwatch")
    quiet_games = tuple(
        name.strip().removesuffix(".exe") for name in games_raw.split(",") if name.strip()
    )
    chat_channel_ids: list[int] = []
    for part in os.getenv("CHAT_CHANNEL_IDS", "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            chat_channel_ids.append(int(part))
        except ValueError as exc:
            raise ConfigError("CHAT_CHANNEL_IDS has to be numeric channel ids separated by commas.") from exc
    from assistant.bedtime_core import parse_clock

    bed_raw = os.getenv("BEDTIME", "on").strip().lower() or "on"
    if bed_raw not in ("on", "off"):
        raise ConfigError("BEDTIME has to be on or off.")
    try:
        bed_start = parse_clock(os.getenv("BEDTIME_START", "20:30").strip() or "20:30")
        bed_end = parse_clock(os.getenv("BEDTIME_END", "04:00").strip() or "04:00")
    except ValueError as exc:
        raise ConfigError("BEDTIME_START and BEDTIME_END have to be times like 20:30 or 8:30pm.") from exc
    try:
        bed_every = int(os.getenv("BEDTIME_EVERY", "30").strip() or "30")
    except ValueError as exc:
        raise ConfigError("BEDTIME_EVERY has to be a number of minutes, like 30.") from exc
    if not 5 <= bed_every <= 180:
        raise ConfigError("BEDTIME_EVERY has to be between 5 and 180 minutes.")
    meds_raw = os.getenv("MEDS", "on").strip().lower() or "on"
    if meds_raw not in ("on", "off"):
        raise ConfigError("MEDS has to be on or off.")
    try:
        meds_start = parse_clock(os.getenv("MEDS_TIME", "9:00").strip() or "9:00")
        meds_until = parse_clock(os.getenv("MEDS_UNTIL", "13:00").strip() or "13:00")
    except ValueError as exc:
        raise ConfigError("MEDS_TIME and MEDS_UNTIL have to be times like 9:00 or 1pm.") from exc
    if meds_until <= meds_start:
        raise ConfigError("MEDS_UNTIL has to be later in the day than MEDS_TIME.")
    try:
        meds_every = int(os.getenv("MEDS_EVERY", "60").strip() or "60")
    except ValueError as exc:
        raise ConfigError("MEDS_EVERY has to be a number of minutes, like 60.") from exc
    if not 10 <= meds_every <= 240:
        raise ConfigError("MEDS_EVERY has to be between 10 and 240 minutes.")
    morning_raw = os.getenv("MORNING_HELLO", "on").strip().lower() or "on"
    if morning_raw not in ("on", "off"):
        raise ConfigError("MORNING_HELLO has to be on or off.")
    try:
        morning_time = parse_clock(os.getenv("MORNING_TIME", "8:00").strip() or "8:00")
    except ValueError as exc:
        raise ConfigError("MORNING_TIME has to be a time like 8:00 or 7:30am.") from exc
    def on_off(name: str, default: str) -> bool:
        raw = os.getenv(name, default).strip().lower() or default
        if raw not in ("on", "off"):
            raise ConfigError(f"{name} has to be on or off.")
        return raw == "on"

    voice_flags = {
        "voice_messages": on_off("VOICE_MESSAGES", "on"),
        "wake_word": on_off("WAKE_WORD", "on"),
        "wake_during_games": on_off("WAKE_DURING_GAMES", "off"),
        "voice_replies": on_off("VOICE_REPLIES", "on"),
        "voice_dm": on_off("VOICE_DM", "on"),
    }
    whisper_device = os.getenv("WHISPER_DEVICE", "cpu").strip().lower() or "cpu"
    if whisper_device not in ("cpu", "cuda"):
        raise ConfigError("WHISPER_DEVICE has to be cpu or cuda.")
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
        pc_enabled=pc_raw == "on",
        chat_channel_ids=tuple(chat_channel_ids),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "").strip() or "openrouter/auto",
        bedtime_enabled=bed_raw == "on",
        bedtime_start=bed_start,
        bedtime_end=bed_end,
        bedtime_every=bed_every,
        meds_enabled=meds_raw == "on",
        meds_start=meds_start,
        meds_until=meds_until,
        meds_every=meds_every,
        meds_name=os.getenv("MEDS_NAME", "").strip(),
        morning_enabled=morning_raw == "on",
        morning_time=morning_time,
        **voice_flags,
        whisper_model=os.getenv("WHISPER_MODEL", "").strip() or "small.en",
        wake_model=os.getenv("WAKE_MODEL", "").strip() or "tiny.en",
        whisper_device=whisper_device,
        mic_device=os.getenv("MIC_DEVICE", "").strip(),
        voice_name=os.getenv("VOICE_NAME", "").strip() or "af_heart",
        kokoro_python=os.getenv("KOKORO_PYTHON", "").strip(),
        kokoro_models=os.getenv("KOKORO_MODELS", "").strip(),
        pc_timeout=pc_timeout,
        quiet_games=quiet_games,
    )
