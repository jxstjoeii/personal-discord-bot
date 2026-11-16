from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

BUILTIN = (
    "assistant.addons.reminders",
    "assistant.addons.notes",
    "assistant.addons.house",
    "assistant.addons.ask",
    "assistant.addons.pc",
    "assistant.addons.jobs",
    "assistant.addons.guide",
)
USER_PREFIX = "user_addons."


async def load_builtin(bot) -> None:
    for name in BUILTIN:
        await bot.load_extension(name)


def _ensure_user_package(directory: Path) -> None:
    import user_addons

    path = str(directory)
    current = list(getattr(user_addons, "__path__", []))
    if path not in current:
        user_addons.__path__.append(path)


async def unload_user_addons(bot) -> None:
    for name, cog in list(bot.cogs.items()):
        module = getattr(cog, "__module__", "")
        if module.startswith(USER_PREFIX):
            await bot.remove_cog(name)
    for key in list(sys.modules):
        if key.startswith(USER_PREFIX):
            del sys.modules[key]


async def load_user_addons(bot, directory: Path) -> tuple[list[str], list[str]]:
    directory.mkdir(parents=True, exist_ok=True)
    _ensure_user_package(directory)
    loaded: list[str] = []
    errors: list[str] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_") or path.name == "__init__.py":
            continue
        module_name = f"{USER_PREFIX}{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise RuntimeError("Could not import this file")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            setup = getattr(module, "setup", None)
            if setup is None:
                raise RuntimeError("Add async def setup(bot) so the addon can load")
            await setup(bot)
            loaded.append(path.stem)
        except Exception as exc:
            log.exception("Failed to load addon %s", path.name)
            sys.modules.pop(module_name, None)
            errors.append(f"{path.name}: {exc}")
    return loaded, errors


async def reload_user_addons(bot, directory: Path) -> tuple[list[str], list[str]]:
    await unload_user_addons(bot)
    return await load_user_addons(bot, directory)


def describe_addons(bot) -> str:
    lines: list[str] = []
    for cog in bot.cogs.values():
        name = getattr(cog, "addon_name", None)
        if not name:
            continue
        description = getattr(cog, "addon_description", "") or ""
        method = getattr(cog, "assistant_tools", None)
        tools = [item.name for item in method()] if callable(method) else []
        line = f"**{name}** — {description}"
        if tools:
            line += f" Tools: {', '.join(tools)}."
        lines.append(line)
    return "\n".join(lines) if lines else "No addons are loaded."
