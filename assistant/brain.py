"""Patricia's link to Claude, through the Claude Agent SDK.

The SDK runs Claude Code in the background, so it can sign in with a Claude
subscription (CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`, or a saved
`claude` login) instead of a paid API key.

Claude Code's own tools (running commands, editing files, browsing) are all
turned off. Claude only gets Patricia's tools, so PC commands still run only
after Joeii presses Yes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from assistant.config import ROOT, Settings
from assistant.tools import AssistantTool, ToolContext, invoke_tool

log = logging.getLogger(__name__)

SERVER = "patricia"
WORKDIR = ROOT / "data" / "claude"

# Claude Code's built-in tools. Listing them here removes them from Claude's
# view, on top of tools=[]. Names that do not exist are ignored.
BUILT_IN_TOOLS = [
    "Agent", "Bash", "BashOutput", "Edit", "ExitPlanMode", "Glob", "Grep", "KillBash",
    "KillShell", "LS", "ListMcpResourcesTool", "Monitor", "MultiEdit", "NotebookEdit",
    "NotebookRead", "PowerShell", "Read", "ReadMcpResourceTool", "Skill", "SlashCommand",
    "Task", "TodoWrite", "ToolSearch", "WebFetch", "WebSearch", "Write",
]


class ClaudeUnavailable(RuntimeError):
    """Claude Code could not start, or is not signed in."""


def system_prompt(settings: Settings, tool_names: list[str]) -> str:
    now = datetime.now(settings.timezone)
    names = ", ".join(tool_names) if tool_names else "none"
    clock = now.strftime("%A, %B %d, %Y %I:%M %p %Z")
    return (
        "You are Patricia, Joeii's private assistant on this PC. "
        "Be calm, brief, and practical. "
        "Speak to Joeii directly. "
        "Use tools for the calendar, the weather, reminders, and notes. "
        "Do not guess what is on the calendar or what the weather is. "
        "The calendar is read-only. You cannot add, change, or delete events. "
        "When Joeii asks you to remember something, save a note. "
        "When Joeii asks to be reminded, create a reminder. "
        "When Joeii wants to find a note, search and then read the matching note before you answer. "
        "Delete a note or cancel a reminder only when clearly asked. "
        "Do not invent ids. Use the ids the tools return. "
        "When Joeii wants something done on his PC, use propose_pc_task. It only sends a plan "
        "with Yes and No buttons. Never say the task already ran. "
        "You have no other way to touch the PC, files, or the web. "
        f"The current local time is {clock}. "
        f"The timezone is {settings.timezone.key}. "
        f"Tools you can use: {names}."
    )


def transcript(history: list[dict], user_text: str) -> str:
    """The SDK takes one prompt, so recent chat goes in as a transcript."""
    lines: list[str] = []
    for item in history:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role not in ("user", "assistant") or not content:
            continue
        speaker = "Joeii" if role == "user" else "Patricia"
        lines.append(f"{speaker}: {content}")
    if not lines:
        return user_text
    return (
        "Recent conversation, for context:\n"
        + "\n\n".join(lines)
        + "\n\nJoeii's new message. Reply to this one:\n"
        + user_text
    )


def _options(settings: Settings, system: str, server, tool_names: list[str], max_turns: int):
    from claude_agent_sdk import ClaudeAgentOptions

    WORKDIR.mkdir(parents=True, exist_ok=True)
    return ClaudeAgentOptions(
        system_prompt=system,
        model=settings.model or None,
        tools=[],
        disallowed_tools=list(BUILT_IN_TOOLS),
        allowed_tools=[f"mcp__{SERVER}__{name}" for name in tool_names],
        mcp_servers={SERVER: server} if server is not None else {},
        strict_mcp_config=True,
        setting_sources=[],
        max_turns=max_turns,
        cwd=str(WORKDIR),
    )


def _sdk_tool(item: AssistantTool, call):
    from claude_agent_sdk import tool

    schema = item.parameters or {"type": "object", "properties": {}}
    schema.setdefault("properties", {})

    async def handler(args: dict) -> dict:
        text = await asyncio.to_thread(call, item.name, args or {})
        return {"content": [{"type": "text", "text": text}]}

    return tool(item.name, item.description, schema)(handler)


async def _ask(settings: Settings, system: str, prompt: str, tools: list[AssistantTool], call, max_turns: int) -> str:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeSDKError,
        CLINotFoundError,
        ResultMessage,
        TextBlock,
        create_sdk_mcp_server,
        query,
    )

    server = None
    if tools:
        server = create_sdk_mcp_server(name=SERVER, tools=[_sdk_tool(item, call) for item in tools])
    options = _options(settings, system, server, [item.name for item in tools], max_turns)
    texts: list[str] = []
    result: ResultMessage | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                texts.extend(block.text for block in message.content if isinstance(block, TextBlock))
            elif isinstance(message, ResultMessage):
                result = message
    except CLINotFoundError as exc:
        raise ClaudeUnavailable("Claude Code was not found. Reinstall with run.ps1.") from exc
    except ClaudeSDKError as exc:
        if result is None:
            raise ClaudeUnavailable(str(exc)) from exc
        log.warning("Claude finished with an error: %s", exc)
    if result is not None and result.is_error and not texts:
        detail = result.result or ", ".join(result.errors or []) or result.subtype
        raise ClaudeUnavailable(detail)
    if result is not None and result.result and not result.is_error:
        return result.result.strip()
    return (texts[-1] if texts else "").strip()


def _run(coro):
    """Called from a worker thread, so a fresh event loop is fine."""
    return asyncio.run(coro)


def run_chat(
    settings: Settings,
    history: list[dict],
    user_text: str,
    tools: list[AssistantTool],
    ctx: ToolContext,
) -> str:
    by_name = {item.name: item for item in tools}
    last_result = ""

    def call(name: str, args: dict) -> str:
        nonlocal last_result
        last_result = invoke_tool(by_name, ctx, name, json.dumps(args))
        log.info("Tool %s finished", name)
        return last_result

    system = system_prompt(settings, [item.name for item in tools])
    text = _run(_ask(settings, system, transcript(history, user_text), tools, call, max_turns=8))
    if text:
        return text
    if last_result:
        return last_result
    return "I couldn't finish that request."


def structured(settings: Settings, system: str, prompt: str, name: str, description: str, schema: dict) -> dict:
    """Ask Claude to answer by calling one tool, and return that tool's input."""
    captured: dict = {}

    def keep(args: dict) -> str:
        captured.clear()
        captured.update(args)
        return "Received. You are done, so stop here."

    spec = AssistantTool(name=name, description=description, parameters=json.loads(json.dumps(schema)), handler=keep)

    def call(tool_name: str, args: dict) -> str:
        return keep(args) if tool_name == name else json.dumps({"error": "Unknown tool"})

    instructions = system + f"\n\nAnswer only by calling the {name} tool exactly once."
    _run(_ask(settings, instructions, prompt, [spec], call, max_turns=3))
    if not captured:
        raise ClaudeUnavailable(f"Claude did not call {name}.")
    return dict(captured)


def claude_status() -> str:
    """Which sign-in Claude Code will use, for the startup log."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return "API key (ANTHROPIC_API_KEY)"
    if os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
        return "Claude subscription token (CLAUDE_CODE_OAUTH_TOKEN)"
    base = Path(os.getenv("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    if (base / ".credentials.json").exists():
        return "saved Claude Code login"
    return ""
