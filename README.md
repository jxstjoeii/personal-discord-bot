# Personal Discord assistant

A private Discord bot for one person. Patricia chats, sets reminders, keeps a catalog of notes, reads the calendar and the weather, and picks up new abilities from the `user_addons` folder.

Only the Discord account in `DISCORD_OWNER_ID` can use it. Reminders, notes, and chat history stay in a database on this computer. Chat, and any note text she looks up while answering, is sent to the xAI API. Calendar and weather are read on this PC and do not need the API key. She can read the calendar. She does not add or change events.

## What you can say

Slash commands:

- `/remind add` sets a reminder. `when` can be `in 20 minutes`, `tomorrow at 9am`, or `friday 5pm`.
- `/remind list` shows what is coming up.
- `/remind cancel` removes one by its id.
- `/note add`, `/note show`, `/note edit`, and `/note delete` manage notes. To clear tags while editing, set tags to `-`.
- `/catalog` browses notes. You can filter with a search or a tag, and page through them.
- `/chat` talks to Patricia. `/ask` does the same thing.
- `/brief` gives the time, the weather, today and tomorrow on the calendar, and upcoming reminders.
- `/calendar` reads today and tomorrow. `/weather` reads the weather at home. These work without the API key.
- `/clear_chat` forgets the recent conversation. Notes and reminders stay.
- `/addons` lists abilities.
- `/reload_addons` loads new files from `user_addons`.
- `/help` shows this list inside Discord.

You can also send a normal message in a DM, or mention the bot in a server. "Remind me in 20 minutes to stretch" and "Save a note called grocery list: oat milk" work that way too.

Reminders arrive as a direct message. The bot checks every 15 seconds, so it has to stay running. If the computer is asleep, a due reminder is sent after it wakes up.

## Set it up

1. Create an application at <https://discord.com/developers/applications>.
2. Open **Bot**, reset the token, and copy it into `.env` as `DISCORD_TOKEN`.
3. On that same Bot page, turn on **Message Content Intent**. Leave **Public Bot** off.
4. In Discord, turn on **Settings → Advanced → Developer Mode**. Right-click your name and choose **Copy User ID**. Put that in `DISCORD_OWNER_ID`.
5. Optional: right-click your server icon, copy the server id, and put it in `DISCORD_GUILD_ID`. Commands then show up in that server right away.
6. Create an API key at <https://console.x.ai/team/default/api-keys> and put it in `XAI_API_KEY`. Reminders, notes, the calendar, and the weather work without it. Chat needs it.
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

`.env` holds the Discord token and the xAI key. `data/assistant.db` holds your notes, reminders, and recent chat. Both are gitignored.
