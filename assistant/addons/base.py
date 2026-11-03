from __future__ import annotations

from discord.ext import commands

from assistant.tools import AssistantTool


class Addon(commands.Cog):
    """Base class for a built-in or user-added ability."""

    addon_name = "addon"
    addon_description = ""

    def __init__(self, bot):
        self.bot = bot

    def assistant_tools(self) -> list[AssistantTool]:
        return []
