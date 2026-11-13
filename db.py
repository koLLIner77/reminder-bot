"""All database code lives here (SQLite ships with Python, nothing to install)."""
import sqlite3
from contextlib import closing

DB_PATH = "reminders.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # lets us read columns by name: row["text"]
    return conn


# `with closing(conn) as conn, conn:` = close the connection at the end,
# and commit the changes (or roll back if an error happens).

def init_db():
    with closing(_connect()) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY, tz TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS reminders ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " chat_id INTEGER NOT NULL,"
            " text TEXT NOT NULL,"
            " due_ts REAL NOT NULL,"                      # unix time (UTC)
            " status TEXT NOT NULL DEFAULT 'pending',"    # pending/done/cancelled/expired
            " nags INTEGER NOT NULL DEFAULT 0)"           # how many times we've sent it
        )


# ---- users ----
def set_tz(chat_id, tz):
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO users (chat_id, tz) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET tz = excluded.tz",
            (chat_id, tz),
        )


def get_tz(chat_id):
    with closing(_connect()) as conn:
        row = conn.execute("SELECT tz FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    return row["tz"] if row else None


# ---- reminders ----
# No placeholders, never put user text into the SQL string
# That is what prevents "SQL injection".

def add_reminder(chat_id, text, due_ts):
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO reminders (chat_id, text, due_ts) VALUES (?, ?, ?)",
            (chat_id, text, due_ts),
        )
        return cur.lastrowid


def get_reminder(rid):
    with closing(_connect()) as conn:
        return conn.execute("SELECT * FROM reminders WHERE id = ?", (rid,)).fetchone()


def count_pending(chat_id):
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM reminders WHERE chat_id = ? AND status = 'pending'",
            (chat_id,),
        ).fetchone()["n"]


def list_pending(chat_id):
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT * FROM reminders WHERE chat_id = ? AND status = 'pending' ORDER BY due_ts",
            (chat_id,),
        ).fetchall()


def all_pending():
    with closing(_connect()) as conn:
        return conn.execute("SELECT * FROM reminders WHERE status = 'pending' ORDER BY due_ts").fetchall()


def set_status(rid, status):
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, rid))


def bump_nags(rid):
    """Add 1 to the send counter and return the new value."""
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE reminders SET nags = nags + 1 WHERE id = ?", (rid,))
        return conn.execute("SELECT nags FROM reminders WHERE id = ?", (rid,)).fetchone()["nags"]


def snooze(rid, new_due_ts):
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE reminders SET due_ts = ?, nags = 0 WHERE id = ?", (new_due_ts, rid))