"""Copy this file to a new name without the leading underscore.

Example: user_addons/ping.py

Rename the class so it does not collide with another addon, then restart
the bot or run /reload_addons in Discord.

Subclass Addon, give it a name and description, and add async def setup(bot).
Slash commands become Discord commands. assistant_tools() lets a normal
message, like a DM, use the ability too.
"""

from __future__ import annotations

import discord
from discord import app_commands

from assistant.addons.base import Addon
from assistant.tools import AssistantTool, ToolContext


class Ping(Addon):
    addon_name = "ping"
    addon_description = "Example ability. Rename this before you use it."

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="ping",
                description="Reply with pong. Use only when the user asks you to ping.",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=self._ping,
            )
        ]

    def _ping(self, ctx: ToolContext) -> str:
        return f"pong for user {ctx.user_id}"

    @app_commands.command(name="ping", description="Check that this addon is loaded")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Pong.")


async def setup(bot) -> None:
    await bot.add_cog(Ping(bot))
