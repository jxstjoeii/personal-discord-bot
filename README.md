# Personal Discord assistant

A private Discord bot for one person. Patricia chats, sets reminders, keeps a catalog of notes, reads the calendar and the weather, and picks up new abilities from the `user_addons` folder.

Only the Discord account in `DISCORD_OWNER_ID` can use it. Reminders, notes, and chat history stay in a database on this computer. Chat, and any note text she looks up while answering, is sent to Claude, through your Claude subscription. Calendar and weather are read on this PC and do not need Claude. She can read the calendar. She does not add or change events.

## What you can say

Slash commands:

- `/remind add` sets a reminder. `when` can be `in 20 minutes`, `tomorrow at 9am`, or `friday 5pm`.
- `/remind list` shows what is coming up.
- `/remind cancel` removes one by its id.
- `/note add`, `/note show`, `/note edit`, and `/note delete` manage notes. To clear tags while editing, set tags to `-`.
- `/catalog` browses notes. You can filter with a search or a tag, and page through them.
- `/chat` talks to Patricia. `/ask` does the same thing.
- `/brief` gives the time, the weather, today and tomorrow on the calendar, and upcoming reminders.
- `/calendar` reads today and tomorrow. `/weather` reads the weather at home, with the next few hours. These work without Claude signed in. Set `WEATHER_LOCATION` in `.env` (a city like `Portland, OR`, or coordinates) to choose where home is. Without it, Patricia uses the location in the morning briefing.
- `/pc` asks Patricia to do something on this PC. See below.
- `/clear_chat` forgets the recent conversation. Notes and reminders stay.
- `/addons` lists abilities.
- `/reload_addons` loads new files from `user_addons`.
- `/help` shows this list inside Discord.

You can also send a normal message in a DM, or mention the bot in a server. "Remind me in 20 minutes to stretch" and "Save a note called grocery list: oat milk" work that way too.

Reminders arrive as a direct message. The bot checks every 15 seconds, so it has to stay running. If the computer is asleep, a due reminder is sent after it wakes up.

## Talking to Patricia

DM her in plain words. You don't need slash commands. In a server, @mention her, reply to one of her messages, or list the channel in `CHAT_CHANNEL_IDS` so she reads everything you write there.

She sets reminders from normal sentences, including repeating ones:

- "remind me to take the chicken out at 5"
- "ping me every 30 minutes to list the nerf until I say stop"
- "every day at 9am remind me to stretch, until friday"

Repeating reminders tell you when the next one is. Reply "stop" or "done" to one and she cancels it. `/remind list` shows them all, and `/remind add` has `every` and `until` options too.

## Bedtime

From 8:30 PM, Patricia DMs you every 30 minutes to get ready for bed. She's firm but kind, gets a little firmer as it gets later, and gives you one concrete next step each time. Every nudge has an **I'm going to bed** button. Pressing it, telling her you're going to bed in chat, or `/bedtime done` stops the nudges for the night. Turning the PC off stops them too, since she runs on it. If the PC comes back on before the night ends (4 AM), she picks up again. `/bedtime status` shows the schedule. Change it with `BEDTIME_START`, `BEDTIME_EVERY`, and `BEDTIME_END` in `.env`, or turn it off with `BEDTIME=off`. If Claude can't be reached, she uses a set of fixed nudges.

## Scheduled jobs

A job is something Patricia does by herself on a schedule. A reminder repeats a fixed message. A job thinks each time: she can check the weather, your calendar, notes, a web search, or a web page, compare with what she found last time, and message you only when there's something worth saying. Ask in plain words:

- "check https://example.com/order/42 every hour and tell me when the status changes, stop once it's delivered"
- "every morning at 8, tell me if I need an umbrella and what's on my calendar"

Each job remembers what it saw last time, so "tell me when it changes" works. It stops by itself when its goal is reached, or at an `until` time. `/jobs list` shows them and `/jobs cancel` stops one, or just ask her. Jobs run at most every 10 minutes, because each run uses your Claude usage. A job that fails 3 times in a row is paused and she tells you why. Pages that only show content with JavaScript, or need a login, can't be read.

## Backup brain

Patricia thinks with your Claude subscription first. If that fails or hits its usage limit, and `OPENROUTER_API_KEY` is set, she switches to OpenRouter for that message, like Heimdall does. She only switches when nothing has happened yet, so an action never runs twice. OpenRouter is pay per use, so set a spending limit on the key. `OPENROUTER_MODEL` picks the model, and `openrouter/auto` lets OpenRouter choose.

## Doing things on this PC

Tell Patricia what you want to happen, with `/pc` or in a normal message: "open my downloads folder", "how much space is left on C:", "turn on dark mode". She writes PowerShell commands and a read-only check, and sends them to you with **Yes** and **No** buttons.

- **No** deletes the message. Nothing runs.
- **Yes** runs the commands one by one, then runs the check. Patricia tells you whether it worked. If it didn't, she says what went wrong and how to fix it, and sends the fix with its own Yes and No buttons.

Only `DISCORD_OWNER_ID` can press the buttons. A plan expires after 60 minutes, and each one can run only once. Commands run hidden, as your normal Windows account, not as administrator, so anything that needs a UAC prompt will fail and she will say so. Chat needs Claude signed in, so this does too.

While a game in `QUIET_GAMES` is running (Overwatch by default), anything she opens goes on the screen Discord is on, not the game screen. She refuses a plan that would open something any other way. If you only have one screen, she won't open anything while the game is running. Run Overwatch in borderless windowed mode so a new window can't pull you out of the game.

Set `PC_COMMANDS=off` in `.env` to turn this off.

## Set it up

1. Create an application at <https://discord.com/developers/applications>.
2. Open **Bot**, reset the token, and copy it into `.env` as `DISCORD_TOKEN`.
3. On that same Bot page, turn on **Message Content Intent**. Leave **Public Bot** off.
4. In Discord, turn on **Settings → Advanced → Developer Mode**. Right-click your name and choose **Copy User ID**. Put that in `DISCORD_OWNER_ID`.
5. Optional: right-click your server icon, copy the server id, and put it in `DISCORD_GUILD_ID`. Commands then show up in that server right away.
6. Sign Patricia in to your Claude subscription (Pro, Max, Team, or Enterprise). After `run.ps1` has installed the packages once, run `.\setup-claude.ps1`. Approve it in the browser and paste the token it prints into `.env` as `CLAUDE_CODE_OAUTH_TOKEN`. The token lasts a year. Patricia's chats count toward your plan's usage limits, the same as using Claude yourself. Reminders, notes, the calendar, and the weather work without it. Chat needs it.

   Patricia talks to Claude through the Claude Agent SDK, which runs Claude Code in the background. Claude Code's own tools for running commands and editing files are turned off, and only its read-only web search stays on, and it does not read your other Claude Code settings. If you'd rather pay per use, put an API key in `ANTHROPIC_API_KEY` instead. It wins over the token when both are set.
7. Invite the bot. In the developer portal, open **OAuth2 → URL Generator**. Choose the scopes `bot` and `applications.commands`. Choose the permissions **View Channels**, **Send Messages**, **Embed Links**, and **Read Message History**. Open the generated URL and add the bot to your server.

Allow direct messages from server members, or the reminder DMs cannot arrive.

```powershell
cd $HOME\Documents\personal-discord-bot
copy .env.example .env
notepad .env
.\run.ps1
```

`run.ps1` creates a virtual environment, installs the packages, and starts the bot. Leave that window open.

The first time, global commands (the ones that work in DMs) can take up to an hour to appear. With `DISCORD_GUILD_ID` set, the server copies show up on startup. Those server copies can make each command appear twice until Discord finishes the global update.

## Add an ability

1. Copy `user_addons/_template.py` to a new file in that folder, without the leading underscore. Example: `user_addons/ping.py`.
2. Rename the class so it is unique.
3. In Discord, run `/reload_addons`.

A user addon is a Python file with `async def setup(bot)` that adds a cog subclassing `Addon`. Put slash commands on the class. Return `AssistantTool` objects from `assistant_tools()` when a normal DM should be able to use the ability too. Files whose names start with `_` are ignored.

Built-in abilities live in `assistant/addons/`. A tool name in a user addon replaces a built-in tool with the same name.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Files that stay off GitHub

`.env` holds the Discord token and your Claude token. `data/assistant.db` holds your notes, reminders, and recent chat. Both are gitignored.
