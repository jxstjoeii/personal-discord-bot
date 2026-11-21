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
- `/calendar` reads today and tomorrow. `/weather` reads the weather at home, with the next few hours. These work without Claude signed in. Set `WEATHER_LOCATION` in `.env` (a city like `Portland, OR`, or coordinates) to choose where home is. Without it, Patricia uses the location in the morning briefing. If Open-Meteo doesn't answer, she tries again over IPv4, then uses the US National Weather Service (weather.gov) as a backup.
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

## Alarms

Discord doesn't let bots make real calls, so an alarm is the next best thing. Say "wake me up at 7am" or "set an alarm for 6:30 tomorrow", or use `/alarm set`. When it goes off, Patricia:

1. DMs you "⏰ Alarm" with a **Stop** and a **Snooze 5 min** button, and
2. beeps out of your PC speakers (in the background, no window opens),

and keeps DMing every 30 seconds until you tap Stop, reply "stop" or "I'm up", or use `/alarm stop`. If you don't answer for 10 minutes, she stops and tells you. A time like "7am" that already passed today means tomorrow. Alarms ring even during class quiet hours, since you set them yourself. If your PC is muted, you'll only get the DMs. `/alarm list` and `/alarm cancel` show and remove alarms.

## Arrival messages

Patricia can DM you when you get to (or leave) a place, like "🏍️ helmet on the hook" at home or "check your parking pass" at school. Your iPhone does the location part with a Shortcuts automation. When you arrive, it posts one short line like `arrive school` to a private channel in your server, and Patricia sends the message you picked. Your GPS location never leaves your phone. Patricia only learns the place name.

1. Make a private text channel in your server, for example `#iphone`, and add Patricia to it. Run `/arrival setup` in it. Patricia replies with a link (a Discord webhook). If she isn't allowed to make one, she tells you how to copy one from the channel settings.
2. Pick messages: `/arrival set place:school message:Park in lot B`, or tell her "when I get home, remind me to plug in my phone". Add `when:leave` for a message when you leave. `/arrival list` shows them, `/arrival test` tries one, `/arrival remove` deletes a place.
3. On your iPhone, open Shortcuts, then Automation, then the plus button, then **Arrive**. Pick the place and choose **Run Immediately**. Add **Get Contents of URL** with the link from step 1, method **POST**, request body **JSON**, and one Text field named `content` with the value `arrive school`. Do one automation for each place.

Patricia reacts to each ping in the channel: ✅ sent, 🤫 held for class quiet hours (she sends it when class ends, or drops it after 2 hours), 🔁 ignored because the same ping came in the last 20 minutes, ❔ she didn't understand it or doesn't know the place yet. It works anywhere your phone has signal, even when the PC is on another network, because the ping goes through Discord. The PC does need to be on.

## Morning hello

At 8:00 AM Patricia DMs you a short good morning: the weather, whether it's a motorcycle riding day (using the riding rules in the morning briefing's `motorcycle` settings), anything due in the next 3 days, today's reminders, and a fun closer: the Overwatch hero of the day with a small challenge, plus a joke or a fun fact. If the PC was off at 8, she sends it when she comes online, until noon. `/morning` shows it any time. Change the time with `MORNING_TIME`, or turn it off with `MORNING_HELLO=off`.

## What she remembers about you

When you tell Patricia something lasting about yourself, like your main heroes, your classes, or how you like reminders, she saves it to `data/about-joeii.md` and uses it in every chat. The `data` folder is in `.gitignore`, so this file never goes to GitHub. It stays on your PC, and it's sent to Claude only as part of your chats. `/aboutme` shows what she knows. Ask her to forget something, or edit the file by hand: one fact per line, starting with `- `.

## Eyes

Send Patricia a picture in a DM (or with an @mention in a server), with or without a question: a screenshot of an error, a photo of homework, two outfits to pick from. She sees up to 4 pictures at a time. Big photos are shrunk first with Pillow, which `run.ps1` installs.

Ask "look at my screen" (or "check my Discord screen") and she takes a screenshot, looks, and answers. She takes it inside her own program with Pillow, so nothing pops up, and it's never saved to disk. She never looks on her own, and scheduled jobs can't use it. While a game in `QUIET_GAMES` is running, the game screen is left out unless you ask her to include it. The screenshot is sent to Claude with that one message, like any picture you send.

## Instant PC controls

Say or type "volume down", "volume up 20", "set volume to 30", "mute", "pause", "skip song", "previous song", "lock my PC", or "turn off my screens". Short commands like these happen right away, with no Yes/No step and no wait for Claude. They press the same media keys your keyboard has. Longer requests that mention these still work; Claude just uses the same controls.

## Mood, birthdays, and recaps

**Mood.** At 7:30 PM Patricia asks how your day was, with buttons from 😞 1 to 😄 5. Reply afterwards if you want to tell her more, and she saves it with the day. If you have a few hard days in a row, she checks in gently. `/mood` logs it any time.

**Birthdays.** "Syl's birthday is March 3" (add the year if you know it). She reminds you 3 days before and on the day at 9 AM, and they show up in the morning hello and recaps. `/birthdays add`, `list`, and `remove` work too.

**Nightly recap.** When you tell her you're going to bed (or tap the 😴 button), she sends a short recap: what you got done, meds, play time, mood, and what's coming tomorrow. If you haven't said good night by 11 PM, it comes anyway. **Weekly recap** on Sundays at 7 PM: wins, meds consistency, play time, how the week felt, and what's coming next week. `/recap` shows either one any time.

## Ears

**Voice messages.** Hold the mic button in your DM with Patricia, talk, and let go. She turns it into text on this PC with Whisper and answers like a typed message, showing "🎙️ I heard: …" so you can see what she understood. Works from your phone too. The first one after a restart can take a little longer while Whisper loads. The model downloads once (about 500 MB for `small.en`) into `data/whisper`.

**Hey Patricia.** Off until you switch it on with `/listen on`. Then say "Hey Patricia, what's the weather?" (or "Hey Patricia", wait for the chime, then ask). She answers out loud with the Heart voice from the morning briefing, and DMs you what you said and her answer. Turn it off with `/listen off`, by telling her in chat, or by saying "Hey Patricia, stop listening". `/listen status` says whether she's listening. While she is, her Discord status ends with 👂 and Windows shows its microphone icon by the clock. She ignores the microphone while Overwatch is running (`WAKE_DURING_GAMES=off`).

Privacy: the microphone is only open while listening is on. Short bits of sound are checked on this PC for "hey Patricia" and thrown away if it isn't there. Nothing is saved to disk. Only the words of your request go to Claude.

## Gaming

Patricia checks once a minute whether a game in `QUIET_GAMES` (Overwatch) is running. When you close it after at least 10 minutes, she DMs a wrap-up: how long you played, from when to when, and your total this week. If it's past bedtime, she nudges you toward bed.

Say "one more game" (or use `/onemore`) and she gives you 20 minutes. If the game is still open then, she pings you, and once more 10 minutes later. If you close it in time, the wrap-up says you kept your word. `/gaming` shows today's and this week's play time. All of this only reads which programs are running. It never opens anything over your game.

## Weekly PC check-up

Every Sunday at 6 PM, Patricia DMs a read-only check-up: free disk space, waiting Windows updates or a pending restart, how long since the PC restarted, whether Tailscale is connected (so Remote Desktop from school works), whether her start-up task is installed, and any errors in her log. `/pchealth` runs it any time. It runs hidden, so nothing flashes on screen.

## Fun

`/roll` (like `2d6`), `/flip`, `/8ball`, and `/hero` (a random Overwatch hero, optionally by role). You can also just ask her in chat. Edit the hero list in `assistant/morning_core.py`.

## Assignments

Tell Patricia what's due: "my history essay is due friday 11:59pm" or "bio test on dec 3". A day with no time counts as 11:59 PM. She reminds you 3 days before and the day before at 5 PM, the morning it's due at 8 AM, and 2 hours before when it's due later in the day. If it's past due, she asks once whether you turned it in. Every reminder has a **✅ Done** button that stops the rest. Ask "what's due?" for the list, or use `/assignments add`, `/assignments list`, and `/assignments done`. You can also tell her a due date moved.

## Medication check-in

At 9:00 AM Patricia DMs you to take your morning meds, with **✅ Took them** and **⏰ Snooze 30 min** buttons. If you don't tap one, she asks again every hour until 1 PM, then lets it go for the day. Tapping ✅, telling her in chat ("took my pills"), or `/meds took` logs it, and she tells you your streak. `/meds status` shows today and the streak. The name of the medication comes from the morning briefing's `medication` list, or set `MEDS_NAME`. Change the times with `MEDS_TIME`, `MEDS_EVERY`, and `MEDS_UNTIL`, or turn it off with `MEDS=off`.

## Bedtime

From 8:30 PM, Patricia DMs you every 30 minutes to get ready for bed. She's firm but kind, gets a little firmer as it gets later, and gives you one concrete next step each time. Every nudge has an **I'm going to bed** button. Pressing it, telling her you're going to bed in chat, or `/bedtime done` stops the nudges for the night. Turning the PC off stops them too, since she runs on it. If the PC comes back on before the night ends (4 AM), she picks up again. `/bedtime status` shows the schedule. Change it with `BEDTIME_START`, `BEDTIME_EVERY`, and `BEDTIME_END` in `.env`, or turn it off with `BEDTIME=off`. If Claude can't be reached, she uses a set of fixed nudges.

## Keep her running

Run this once from the bot folder:

```powershell
.\install-startup.ps1
```

It adds a Windows scheduled task named "Patricia Bot". She starts by herself about 20 seconds after you sign in, with no window, so nothing can be closed by accident or flash over a game. If she stops for any reason, the task brings her back within 5 minutes. Her log is at `%LOCALAPPDATA%\PatriciaBot\bot.log`.

- After `.\sync.ps1` pulls an update, run `.\restart.ps1`.
- `.\run.ps1` still works for watching her in a window. Close that window and the background copy takes over within 5 minutes.
- `.\install-startup.ps1 -Remove` stops her from starting by herself.
- If you have an hourly task that runs `sync.ps1`, `.\install-startup.ps1` switches it to `sync-hidden.vbs`, so the sync runs with no window instead of flashing a command prompt every hour.

## Status

Patricia's Discord status follows the time and what you're doing, and changes to a new line every 15 minutes: Overwatch lines while a game in `QUIET_GAMES` is running, bossy bedtime lines after `BEDTIME_START` until you go to bed, sleepy ones after you say good night, and morning, daytime, and evening sets the rest of the time. Edit the lines in `assistant/status_core.py`.

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
