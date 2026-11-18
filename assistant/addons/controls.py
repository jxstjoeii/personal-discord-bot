from __future__ import annotations

from assistant import pc_controls
from assistant.addons.base import Addon
from assistant.tools import AssistantTool


class Controls(Addon):
    addon_name = "controls"
    addon_description = "Instant PC controls: volume, music, lock, and screens off."

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="pc_control",
                description=(
                    "Instantly control the PC: volume_up, volume_down, set_volume (amount = percent), "
                    "mute (toggles), play_pause, next_track, previous_track, lock, screens_off. Use for "
                    "these simple things instead of propose_pc_task; no approval is needed."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": pc_controls.ACTIONS},
                        "amount": {"type": "integer", "description": "Percent, for volume changes."},
                    },
                    "required": ["action"],
                },
                handler=lambda ctx, action, amount=None: pc_controls.run(action, amount),
            )
        ]


async def setup(bot) -> None:
    await bot.add_cog(Controls(bot))
