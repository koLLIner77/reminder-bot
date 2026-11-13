# Reminder Bot

A Telegram reminder bot that **keeps nagging until you tap Done**.

Most reminders get one notification and are easy to swipe away and forget. This bot repeats the reminder every few minutes until you mark it done or snooze it.

<img width="800" height="702" alt="image" src="https://github.com/user-attachments/assets/e407faed-ff3c-403f-be01-84c01d0bb91c" />

## Features

- Natural time formats: `10m`, `2h`, `18:30`, `tomorrow 09:00`, `2026-12-01 09:00`
- **Done** and **Snooze** buttons on every reminder
- Repeats the reminder every 5 minutes (up to 5 times) until you respond
- Reminders are saved in a database, so they survive a restart
- Per-chat time zones (`/timezone Asia/Tashkent`)
- Built-in limits to prevent abuse

## Commands

| Command | What it does |
|---|---|
| `/remind 10m call mom` | Remind me in 10 minutes (`m`, `h`, `d` work) |
| `/remind 18:30 gym` | Today at 18:30, or tomorrow if that time has passed |
| `/remind tomorrow 09:00 essay draft` | Tomorrow at 09:00 |
| `/remind 2026-12-01 09:00 deadline` | A specific date and time |
| `/list` | Show pending reminders |
| `/cancel <id>` | Cancel a reminder (id is shown in `/list`) |
| `/timezone Asia/Tashkent` | Set your time zone. Needed for clock times like `18:30` |

Relative times (`10m`, `2h`) work without setting a time zone.

## Setup

**Requirements:** Python 3.10+ and a bot token from [@BotFather](https://t.me/BotFather).

```bash
git clone https://github.com/YOUR-USERNAME/reminder-bot.git
cd reminder-bot
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Set your bot token as an environment variable (never put it in the code):

```bash
# Windows PowerShell
$env:TELEGRAM_BOT_TOKEN="your-token-here"

# Mac/Linux
export TELEGRAM_BOT_TOKEN="your-token-here"
```

Run it:

```bash
python bot.py
```

The bot only works while this program is running.

## How it works

```
bot.py        Telegram handlers, scheduling, the nagging logic
db.py         All SQLite code (users and reminders tables)
timeparse.py  Turns "tomorrow 09:00" into a UTC timestamp
```

**Life of a reminder**

1. `/remind` parses the time, validates it against the limits, and saves the reminder to SQLite with the status `pending`.
2. The bot schedules a job for the due time using python-telegram-bot's job queue.
3. When the job fires, the bot sends the reminder with **Done** and **Snooze** buttons, then schedules the next nag.
4. **Done** marks it finished and cancels the pending nag. **Snooze** pushes it back 10 minutes. If you ignore it, it repeats up to 5 times and then expires.
5. On startup, the bot reloads every `pending` reminder from the database and schedules it again.

## Design decisions

- **Nagging instead of a single notification.** The point of a reminder is that you act on it, so it repeats until you respond. The interval and maximum count are constants at the top of `bot.py`.
- **Limits are enforced in code.** Reminder length (200 characters), pending reminders per chat (20), how far ahead (365 days), and nags per reminder (5) are checked by the program, not requested politely from users.
- **The database is the source of truth.** Scheduled jobs live in memory and disappear on restart, so every pending reminder is also stored in SQLite and rescheduled at startup. Finished reminders keep their row with a status (`done`, `cancelled`, `expired`) instead of being deleted.
- **Local work before network calls.** In the button handler, the database and scheduler are updated first and Telegram is contacted afterward. If Telegram is slow or times out, a reminder is never left nagging after you pressed Done.
- **Buttons are checked for ownership.** A button press only works if it comes from the chat that owns the reminder.
- **Parameterized SQL.** All queries use `?` placeholders rather than building SQL from user text, which prevents SQL injection.
- **Separated responsibilities.** Time parsing and database code are separate from the bot code, so each part can be read and tested on its own.

## Known limitations

- **The bot must be running to send reminders.** It uses polling, so a reminder due while the bot is offline is sent when the bot restarts, not on time.
- **Messages sent while the bot is offline are dropped** (`drop_pending_updates=True`). This keeps old test commands from replaying during development, but a `/remind` sent during downtime is lost.
- If a user blocks the bot, sending fails and that reminder stays `pending` until the next restart.
- After a restart, a reminder that was mid-nagging fires immediately instead of waiting out the rest of its interval.
- Each nag is a separate message, so buttons on older nag messages stay visible (pressing them says the reminder is no longer active).
- Database calls are synchronous. That is fine at this scale but would need changing for heavy traffic.

## Ideas for next steps

- Natural-language reminders ("remind me Friday after lunch") using an LLM tool that calls the same `add_reminder` logic
- A per-minute rate limit per user
- Tests for `timeparse.py` and the limit checks
- Hosting on a server so the bot runs all the time

## Built with

Python, [python-telegram-bot](https://python-telegram-bot.org/) (with the job queue extra), and SQLite.


