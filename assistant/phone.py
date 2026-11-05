from __future__ import annotations

import logging
import secrets
from pathlib import Path

from aiohttp import web

log = logging.getLogger(__name__)
ICON_PATH = Path(__file__).with_name("phone-icon.png")

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Patricia">
<title>Patricia</title>
<link rel="apple-touch-icon" href="/icon.png">
<link rel="icon" href="/icon.png">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #16141c;
    color: #f4f1ea;
  }
  main { max-width: 40rem; margin: 0 auto; padding: 1.25rem 1rem 6rem; }
  h1 { font-size: 1.7rem; margin: 0.2rem 0; }
  p { line-height: 1.45; }
  .muted { color: #b7b1c4; }
  form, .card { display: grid; gap: 0.75rem; }
  input, textarea, button {
    font: inherit;
    border-radius: 14px;
    border: 1px solid #3a3548;
    background: #221f2b;
    color: inherit;
    padding: 0.85rem 1rem;
  }
  textarea { min-height: 5.5rem; resize: vertical; }
  button {
    background: #efe7ff;
    color: #241b33;
    font-weight: 650;
  }
  button.secondary { background: transparent; color: #efe7ff; }
  .actions { display: flex; gap: 0.5rem; }
  .actions button { flex: 1; }
  .bubble {
    white-space: pre-wrap;
    background: #2a2438;
    border-radius: 16px;
    padding: 0.9rem 1rem;
    margin-top: 1rem;
  }
  .you { background: #31281f; }
  ol { padding-left: 1.2rem; }
  li { margin: 0.4rem 0; }
  code { font-size: 0.95em; }
</style>
</head>
<body>
<main>
  <p class="muted">Patricia</p>
  <h1>Chat with Patricia</h1>
  <p class="muted">Calendar, weather, reminders, and notes stay on this PC. A due reminder still arrives as a Discord message.</p>
  <form id="unlock">
    <label for="token">Phone key from the .env file, the PHONE_TOKEN line</label>
    <input id="token" autocomplete="off" autocapitalize="none" spellcheck="false">
    <button type="submit">Save on this phone</button>
  </form>
  <form id="ask" hidden>
    <div class="actions">
      <button type="button" data-ask="brief">Brief</button>
      <button type="button" data-ask="calendar">Calendar</button>
      <button type="button" data-ask="weather">Weather</button>
    </div>
    <label for="text">What do you need?</label>
    <textarea id="text" placeholder="What's on today?"></textarea>
    <button type="submit">Send</button>
    <button class="secondary" id="forget" type="button">Forget the phone key</button>
  </form>
  <div id="thread"></div>
  <section>
    <h2>Home screen</h2>
    <ol>
      <li>In Safari, tap the Share button.</li>
      <li>Tap Add to Home Screen.</li>
      <li>Name it Patricia, then tap Add.</li>
    </ol>
    <h2>Siri</h2>
    <ol>
      <li>Open Shortcuts and tap the plus button.</li>
      <li>Add Dictate Text. Turn on Stop Listening on Pause.</li>
      <li>Add Get Contents of URL. Set the address to <code id="endpoint"></code>, method to POST, and the body to JSON.</li>
      <li>Add a header named Authorization. The value is Bearer, a space, then the same phone key.</li>
      <li>Set the JSON field text to the Dictated Text variable.</li>
      <li>Add Get Dictionary from Input, then Get Dictionary Value for the key reply.</li>
      <li>Add Speak Text and Show Result, both using that reply.</li>
      <li>Name the shortcut Patricia. Then say, Hey Siri, Patricia.</li>
    </ol>
    <p class="muted">This address works on the same Wi-Fi as the PC. Away from home, install Tailscale on both and use the PC's Tailscale address with the same port.</p>
  </section>
</main>
<script>
const endpoint = location.origin + "/message";
document.getElementById("endpoint").textContent = endpoint;
const unlock = document.getElementById("unlock");
const ask = document.getElementById("ask");
const tokenInput = document.getElementById("token");
const text = document.getElementById("text");
const thread = document.getElementById("thread");

function savedToken() {
  return localStorage.getItem("patriciaToken") || "";
}
function showAsk() {
  unlock.hidden = true;
  ask.hidden = false;
}
if (savedToken()) showAsk();

unlock.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = tokenInput.value.trim();
  if (!value) return;
  localStorage.setItem("patriciaToken", value);
  tokenInput.value = "";
  showAsk();
});
document.getElementById("forget").addEventListener("click", () => {
  localStorage.removeItem("patriciaToken");
  ask.hidden = true;
  unlock.hidden = false;
});

function addBubble(className, value) {
  const node = document.createElement("p");
  node.className = "bubble " + className;
  node.textContent = value;
  thread.prepend(node);
}

async function send(message) {
  if (!message) return;
  addBubble("you", message);
  let reply = "Patricia could not be reached. The PC has to be on, and this phone has to be on the same Wi-Fi.";
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + savedToken(),
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ text: message })
    });
    const payload = await response.json();
    reply = payload.reply || payload.error || reply;
    if (response.status === 401) {
      localStorage.removeItem("patriciaToken");
      ask.hidden = true;
      unlock.hidden = false;
    }
  } catch (error) {
    reply = "Patricia could not be reached. The PC has to be on, and this phone has to be on the same Wi-Fi.";
  }
  addBubble("", reply);
  if ("speechSynthesis" in window) {
    const spoken = new SpeechSynthesisUtterance(reply);
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(spoken);
  }
}

ask.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = text.value.trim();
  text.value = "";
  send(message);
});
document.querySelectorAll("[data-ask]").forEach((button) => {
  button.addEventListener("click", () => send(button.dataset.ask));
});
</script>
</body>
</html>
"""


def authorized(header: str | None, token: str) -> bool:
    if not token or not header:
        return False
    scheme, _, given = header.partition(" ")
    if scheme.lower() != "bearer" or not given:
        return False
    return secrets.compare_digest(given, token)


async def read_text(request: web.Request) -> str:
    if request.method == "GET":
        return str(request.query.get("text", ""))
    content_type = request.headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:
            return ""
        if isinstance(payload, dict):
            return str(payload.get("text", ""))
        return ""
    if "application/x-www-form-urlencoded" in content_type:
        form = await request.post()
        return str(form.get("text", ""))
    raw = await request.text()
    return raw


def phone_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", home)
    app.router.add_get("/icon.png", icon)
    app.router.add_get("/message", message)
    app.router.add_post("/message", message)
    return app


async def home(_: web.Request) -> web.Response:
    return web.Response(text=PAGE, content_type="text/html")


async def icon(_: web.Request) -> web.Response:
    if not ICON_PATH.is_file():
        raise web.HTTPNotFound()
    return web.Response(body=ICON_PATH.read_bytes(), content_type="image/png")


async def message(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    if not authorized(request.headers.get("Authorization"), bot.settings.phone_token):
        return web.json_response({"error": "That phone key was rejected."}, status=401)
    text = (await read_text(request)).strip()
    if not text:
        return web.json_response({"error": "Tell Patricia what you need."}, status=400)
    ask = bot.get_cog("Ask")
    if ask is None:
        return web.json_response({"error": "Patricia is still starting."}, status=503)
    reply = await ask.reply_for_user(bot.settings.owner_id, text, source="Phone")
    return web.json_response({"reply": reply})


async def start_phone(bot) -> web.AppRunner | None:
    token = bot.settings.phone_token
    if not token:
        log.info("Phone page is off. Set PHONE_TOKEN in .env to use the iPhone.")
        return None
    runner = web.AppRunner(phone_app(bot))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", bot.settings.phone_port)
    await site.start()
    log.info("Phone page is listening on port %s", bot.settings.phone_port)
    return runner
