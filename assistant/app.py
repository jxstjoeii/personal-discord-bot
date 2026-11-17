from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from assistant.brain import claude_status
from assistant.channel_log import format_log, write_log
from assistant.config import ConfigError, Settings, load_settings
from assistant.db import Database
from assistant.loader import load_builtin, load_user_addons
from assistant.phone import start_phone

log = logging.getLogger(__name__)


class PrivateTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == interaction.client.settings.owner_id


class AssistantBot(commands.Bot):
    def __init__(self, settings: Settings, db: Database):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            tree_cls=PrivateTree,
            help_command=None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.settings = settings
        self.db = db
        self.phone_runner = None
        self.tree.allowed_contexts = app_commands.AppCommandContext(
            guild=True,
            dm_channel=True,
            private_channel=True,
        )
        self.tree.allowed_installs = app_commands.AppInstallationType(guild=True, user=True)

    async def setup_hook(self) -> None:
        signed_in = claude_status()
        if signed_in:
            log.info("Claude sign-in: %s", signed_in)
        else:
            log.warning("Claude is not signed in. Chat and /pc need it. Run setup-claude.ps1.")
        self.tree.error(self.on_tree_error)
        await load_builtin(self)
        loaded, errors = await load_user_addons(self, self.settings.user_addons_path)
        for error in errors:
            log.error("Addon error: %s", error)
        log.info("User addons: %s", ", ".join(loaded) if loaded else "none")
        try:
            self.phone_runner = await start_phone(self)
        except Exception:
            log.exception("Phone page failed to start")
        await self.sync_commands()

    async def sync_commands(self) -> None:
        if self.settings.guild_id is not None:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %s commands to server %s", len(synced), self.settings.guild_id)
        synced = await self.tree.sync()
        log.info("Synced %s global commands", len(synced))

    async def on_ready(self) -> None:
        status = self.get_cog("Status")
        if status is not None:
            # After a reconnect, set the status again on the next check.
            status._mood = None
        log.info("Logged in as %s", self.user)
        if self.settings.log_channel_id is not None and not getattr(self, "_announced_log", False):
            self._announced_log = True
            await write_log(
                self,
                format_log(
                    self.settings.timezone,
                    "Started",
                    reply="Phone messages, DMs, commands, and delivered reminders will be copied here.",
                ),
            )

    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command,
    ) -> None:
        if command.qualified_name in {"ask", "chat"}:
            return
        details = []
        namespace = getattr(interaction, "namespace", None)
        values = getattr(namespace, "__dict__", {})
        for key, value in values.items():
            if key.startswith("_") or value is None or value == "":
                continue
            details.append(f"{key}: {value}")
        await write_log(
            self,
            format_log(
                self.settings.timezone,
                f"/{command.qualified_name}",
                "\n".join(details),
            ),
        )

    async def close(self) -> None:
        try:
            await super().close()
        finally:
            if self.phone_runner is not None:
                await self.phone_runner.cleanup()
            self.db.close()

    async def on_tree_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        original = getattr(error, "original", error)
        private = isinstance(error, app_commands.CheckFailure) or isinstance(
            original, app_commands.CheckFailure
        )
        if private:
            log.info("Ignored a command from user %s", interaction.user.id)
            message = "This assistant is private."
        else:
            log.exception("Command failed", exc_info=error)
            message = "That command failed. The details are in the bot window."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=private)
            else:
                await interaction.response.send_message(message, ephemeral=private)
        except discord.HTTPException:
            log.exception("Could not send the error message")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = load_settings()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc
    db = Database(settings.database_path)
    bot = AssistantBot(settings, db)
    bot.run(settings.discord_token, log_handler=None)
