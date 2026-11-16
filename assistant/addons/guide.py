from __future__ import annotations

import logging

import discord
from discord import app_commands

from assistant.addons.base import Addon
from assistant.loader import describe_addons, reload_user_addons

log = logging.getLogger(__name__)

HELP = "\n".join(
    [
        "/remind add — set a reminder, such as when: in 20 minutes",
        "/remind list — upcoming reminders",
        "/remind cancel — cancel one by its id",
        "/note add — save a note",
        "/note show — open a note by id",
        "/note edit — change a note",
        "/note delete — delete a note",
        "/catalog — browse and search notes",
        "/chat — talk to Patricia",
        "/ask — same as /chat",
        "/brief — time, weather, calendar, and reminders",
        "/calendar — today and tomorrow, read only",
        "/weather — the weather at home",
        "/jobs list and /jobs cancel — scheduled jobs. Ask in chat to make one, like: check this page every hour",
        "/pc — have Patricia do something on this PC. You see the commands and press Yes or No first",
        "/clear_chat — forget the recent conversation",
        "/addons — list abilities",
        "/reload_addons — load new files from user_addons",
        "You can also DM me, or mention me. A normal sentence can set a reminder, save a note, or ask what is on today.",
        "Say brief, calendar, or weather on their own and I answer without waiting on chat.",
        "New abilities go in the user_addons folder. Copy _template.py, rename it, then run /reload_addons.",
    ]
)


class Guide(Addon):
    addon_name = "guide"
    addon_description = "Lists abilities and reloads new ones from user_addons."

    @app_commands.command(name="help", description="Show what this assistant can do")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Patricia",
            description=HELP[:4000],
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="addons", description="List loaded abilities")
    async def addons(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Abilities",
            description=describe_addons(self.bot)[:4000],
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Add a Python file to user_addons, then run /reload_addons.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="reload_addons", description="Reload abilities from user_addons")
    async def reload_addons(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        loaded, errors = await reload_user_addons(self.bot, self.bot.settings.user_addons_path)
        try:
            await self.bot.sync_commands()
            sync_note = "Slash commands were synced."
        except Exception as exc:
            log.exception("Syncing commands failed")
            sync_note = f"Reload finished, but syncing commands failed: {exc}"
        lines = [f"Loaded: {', '.join(loaded) if loaded else 'none'}", sync_note]
        if errors:
            lines.append("Errors:\n" + "\n".join(errors))
        lines.append("In a server, new commands show up quickly. In DMs they can take up to an hour the first time.")
        await interaction.followup.send("\n".join(lines)[:1900])


async def setup(bot) -> None:
    await bot.add_cog(Guide(bot))
