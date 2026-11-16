"""The parts of scheduled jobs that do not need Discord."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

from assistant.brain import agent, system_prompt
from assistant.formatting import format_stored
from assistant.timeparse import describe_every
from assistant.tools import AssistantTool, ToolContext, invoke_tool

MIN_JOB_MINUTES = 10
MAX_FAILURES = 3
PAGE_LIMIT = 12000
JOB_ONLY_TOOLS = {"create_job"}

FINISH_TOOL = {
    "type": "object",
    "properties": {
        "notify": {
            "type": "boolean",
            "description": "True to message Joeii now. False when nothing is worth telling him.",
        },
        "message": {"type": "string", "description": "What to tell Joeii. Short and plain."},
        "remember": {
            "type": "string",
            "description": "What to remember for the next run, such as the last status seen.",
        },
        "done": {
            "type": "boolean",
            "description": "True when the job's goal is reached and it should stop for good.",
        },
    },
    "required": ["notify", "message", "remember", "done"],
}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs) -> None:
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"):
            self.parts.append("\n")

    def handle_endtag(self, tag) -> None:
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def fetch_page(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, flags=re.I):
        return "Only http and https links can be read."
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Patricia/1.0",
            "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(2_000_000)
            kind = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        return f"The page answered with error {exc.code}."
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return f"Could not open the page: {exc}"
    text = raw.decode(charset, "replace")
    title = ""
    if "html" in kind:
        parser = _Text()
        try:
            parser.feed(text)
        except Exception:
            pass
        title = " ".join(parser.title.split())
        text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    if len(text) > PAGE_LIMIT:
        text = text[:PAGE_LIMIT] + "\n…(page cut off)"
    header = f"URL: {final_url}\n" + (f"Title: {title}\n" if title else "")
    return header + "\n" + (text or "The page had no readable text. It may need JavaScript.")


def run_job(settings, job: dict, tools: list[AssistantTool], ctx: ToolContext) -> dict:
    """Runs one job in a worker thread. Returns what finish_job was given."""
    finished: dict = {}

    def finish(ctx, notify: bool = False, message: str = "", remember: str = "", done: bool = False) -> str:
        finished.update(notify=bool(notify), message=message, remember=remember, done=bool(done))
        return "Saved. You are done."

    finish_tool = AssistantTool("finish_job", "Report the result of this run. Call it exactly once, last.", FINISH_TOOL, finish)
    usable = [item for item in tools if item.name not in JOB_ONLY_TOOLS] + [finish_tool]
    by_name = {item.name: item for item in usable}

    def call(name: str, args: dict) -> str:
        return invoke_tool(by_name, ctx, name, json.dumps(args))

    tz = settings.timezone
    last = format_stored(job["last_run_at"], tz) if job.get("last_run_at") else "never"
    system = system_prompt(settings, list(by_name)) + (
        "\n\nRight now you are running a scheduled job on your own. Nobody is watching, so do "
        "not ask questions. Do the job with your tools, then call finish_job. Set notify to "
        "false when there is nothing new or worth saying, unless the job asks for a report "
        "every time. Put anything you will need to compare next time in remember. Set done "
        "when the job's goal is reached, like 'tell me when it ships' and it has shipped. Do "
        "not create reminders or PC tasks unless the job asks for them."
    )
    prompt = (
        f"Job #{job['id']}, which runs {describe_every(int(job['repeat_minutes']))}:\n"
        f"{job['instruction']}\n\n"
        f"Last run: {last}.\n"
        f"What you remembered last time: {job.get('memory') or 'nothing yet, this is the first run.'}"
    )
    text = agent(settings, system, prompt, usable, call, max_turns=12)
    if not finished:
        # The brain answered in words without calling finish_job.
        finished = {"notify": bool(text), "message": text, "remember": job.get("memory", ""), "done": False}
    return finished
