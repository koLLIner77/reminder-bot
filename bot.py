import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import db
from timeparse import NeedTimezone, parse_when

# put your token as an environment variable
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# ---- Limits. Enforced in code, because we never trust what users type. ----
MAX_TEXT = 200        # characters per reminder
MAX_PENDING = 20      # active reminders per chat
MAX_DAYS = 365        # how far ahead a reminder may be
NAG_EVERY_MIN = 5     # the twist: repeat until the user taps Done
MAX_NAGS = 5          # total sends per reminder, then it expires
SNOOZE_MIN = 10

HELP = (
    "I remind you, and I keep nagging until you tap Done.\n\n"
    "/remind 10m call mom\n"
    "/remind 2h submit the form\n"
    "/remind 18:30 gym  (today, or tomorrow if passed)\n"
    "/remind tomorrow 09:00 essay draft\n"
    "/remind 2026-12-01 09:00 deadline\n\n"
    "/list - your pending reminders\n"
    "/cancel <id> - cancel one\n"
    "/timezone Asia/Tashkent - set your time zone (needed for clock times)"
)


# ---------- scheduling helpers ----------
def schedule(job_queue, rid, delay_seconds):
    """Schedule a reminder to be sent after delay_seconds."""
    job_queue.run_once(fire, when=max(delay_seconds, 1), data=rid, name=f"rem-{rid}")


def cancel_jobs(job_queue, rid):
    for job in job_queue.get_jobs_by_name(f"rem-{rid}"):
        job.schedule_removal()


def keyboard(rid):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Done", callback_data=f"done:{rid}"),
        InlineKeyboardButton(f"😴 Snooze {SNOOZE_MIN}m", callback_data=f"snooze:{rid}"),
    ]])


async def fire(context: ContextTypes.DEFAULT_TYPE):
    """Runs when a reminder is due. Sends it, then schedules the next nag."""
    rid = context.job.data
    r = db.get_reminder(rid)
    if r is None or r["status"] != "pending":
        return  # it was cancelled or finished while we waited

    nags = db.bump_nags(rid)
    prefix = "⏰" if nags == 1 else f"🔁 ({nags}/{MAX_NAGS})"
    await context.bot.send_message(r["chat_id"], f"{prefix} {r['text']}", reply_markup=keyboard(rid))

    if nags < MAX_NAGS:
        schedule(context.job_queue, rid, NAG_EVERY_MIN * 60)
    else:
        db.set_status(rid, "expired")


async def post_init(app: Application):
    """On startup: re-schedule every pending reminder from the database."""
    for i, r in enumerate(db.all_pending()):
        schedule(app.job_queue, r["id"], (r["due_ts"] - time.time()) + i * 0.5)


# ---------- commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)



async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Example: /timezone Asia/Tashkent")
        return
    name = context.args[0]
    try:
        ZoneInfo(name)  # just checking that it's a real time zone
    except (ZoneInfoNotFoundError, ValueError):
        await update.message.reply_text("Unknown time zone. Example: /timezone Asia/Tashkent")
        return
    db.set_tz(update.effective_chat.id, name)
    await update.message.reply_text(f"Time zone set to {name}.")


async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    tz_name = db.get_tz(chat_id)
    tz = ZoneInfo(tz_name) if tz_name else None

    try:
        due, used = parse_when(context.args, tz)
    except NeedTimezone:
        await update.message.reply_text("For clock times I need your time zone first, e.g. /timezone Asia/Tashkent")
        return
    except ValueError:
        await update.message.reply_text(HELP)
        return

    text = " ".join(context.args[used:]).strip()
    due_ts, now = due.timestamp(), time.time()

    error = None
    if not text:
        error = "Add some text after the time."
    elif len(text) > MAX_TEXT:
        error = f"Too long (max {MAX_TEXT} characters)."
    elif due_ts <= now:
        error = "That time is in the past."
    elif due_ts - now > MAX_DAYS * 86400:
        error = f"Too far ahead (max {MAX_DAYS} days)."
    elif db.count_pending(chat_id) >= MAX_PENDING:
        error = f"You already have {MAX_PENDING} pending reminders. Use /cancel <id> or finish some."
    if error:
        await update.message.reply_text(error)
        return

    rid = db.add_reminder(chat_id, text, due_ts)
    schedule(context.job_queue, rid, due_ts - now)

    if tz:
        when = "for " + due.astimezone(tz).strftime("%a %d %b, %H:%M")
    else:
        when = f"in {round((due_ts - now) / 60)} min"
    await update.message.reply_text(f"✅ #{rid} set {when}: {text}")


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    rows = db.list_pending(chat_id)
    if not rows:
        await update.message.reply_text("No pending reminders.")
        return
    tz_name = db.get_tz(chat_id)
    tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    label = tz_name or "UTC (set yours with /timezone)"
    lines = [
        f"#{r['id']}  {datetime.fromtimestamp(r['due_ts'], tz):%a %d %b %H:%M}  {r['text']}"
        for r in rows
    ]
    await update.message.reply_text(f"Times in {label}:\n" + "\n".join(lines))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        rid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /cancel <id>  (see /list)")
        return
    r = db.get_reminder(rid)
    if r is None or r["chat_id"] != chat_id or r["status"] != "pending":
        await update.message.reply_text("No pending reminder with that id.")
        return
    cancel_jobs(context.job_queue, rid)
    db.set_status(rid, "cancelled")
    await update.message.reply_text(f"Cancelled #{rid}.")


# ---------- buttons ----------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    action, rid = query.data.split(":")
    rid = int(rid)
    r = db.get_reminder(rid)
    # Security: only the chat that owns the reminder may press its buttons.
    active = r is not None and r["chat_id"] == update.effective_chat.id and r["status"] == "pending"

    if not active:
        new_text = "This reminder is no longer active."
    else:
        cancel_jobs(context.job_queue, rid)  # stop any scheduled nag
        if action == "Done":
            db.set_status(rid, "done")
            new_text = f"✅ {r['text']} (done)"
        else: #snooze
            db.snooze(rid, time.time() + SNOOZE_MIN * 60)
            schedule(context.job_queue, rid, SNOOZE_MIN * 60)
            new_text = f"😴 {r['text']} (snoozed {SNOOZE_MIN} min)"

    try:
        await query.answer()
        await query.edit_message_text(new_text)
    except TelegramError as e:
        print("Telegram error while answering button:", repr(e))

def main():
    db.init_db()
    app = (
    Application.builder()
    .token(TOKEN)
    .connect_timeout(20)
    .read_timeout(20)
    .write_timeout(20)
    .pool_timeout(20)
    .get_updates_connect_timeout(20)
    .get_updates_read_timeout(20)
    .get_updates_write_timeout(20)
    .get_updates_pool_timeout(20)
    .post_init(post_init)
    .build()
    )
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(CommandHandler("list", list_reminders))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("timezone", set_timezone))
    app.add_handler(CallbackQueryHandler(on_button))
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    

if __name__ == "__main__":
    main()
